#!/usr/bin/env python
# -*- coding: utf-8 -*-

# GIMP plugin to improve on the text-along-path button in the Text tool.
# (c) Ofnuts 2012, 2017
#
#   History:
#
#   v0.0: 2012-04-08    * First published version
#   v0.1: 2012-04-09    * Remove trace (can cause Windows failure)
#                       * Check for missing text and font
#                       * Force workimage size args to int
#   v0.2: 2012-04-11    * Register to work from a Text layer
#   v0.3: 2012-12-12    * Fix to support non-ASCII characters
#                       * Remove text layer access for Gimp > 2.6
#   v0.4: 2014-02-29    * Fix undo stack handling around exceptions (thanks Jörg)
#   v1.0: 2017-10-05    * Remove 2.6 stuff 
#                       * Fix the positioning of characters (no more residual jitter)
#                       * Add "repeat" option 
#                       * Add "reverse path direction" option
#                       * Add "keep boxes" option
#                       * Fix handling of closed strokes
#                       * Improve performance (paths not added to image unless necessary)      
#                       * New "ofn-" naming/packaging
#   v1.1: 2017-10-25    * Remove "box-margins" on first/last characters
#                       * Run on multiple strokes
#                       * Add more path generation options
#   v1.2: 2017-11-07    * Fix bug on width in "Repeated" layout on closed strokes
#                       * Include spacer in the name of produced paths
#   v1.3: 2017-11-07    * Fix broken Left/Right/Centered layouts
#                       * Refactor code
#   v1.4: 2017-11-18    * Add multiple words to strokes
#   v1.5: 2019-07-30    * Fix bug/typo with boxes (thanks Teapot)
#   v1.6: 2019-09-15    * Add top/middle of lowercase (thanks EsperMaschine)
#                      
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 2 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the Free Software
#   Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

# If you alter this program and redistribute it, please make it clear
# that you are the author/maintainer of that version. Thank you.

import math, random, os, sys, copy, itertools
import traceback

from collections import namedtuple
from gimpfu import *
  
debug='OFN_DEBUG' in os.environ
  
def trace(s):
    if debug:
        print s

# Init with [(symbol,label)...((symbol,label)]
def createOpts(name,pairs):
    optsclass=namedtuple(name+'Type',[symbol for symbol,label in pairs]+['labels','labelTuples'])
    opts=optsclass(*(
                    range(len(pairs))
                    +[[label for symbol,label in pairs]]
                    +[[(label,i) for i,(symbol,label) in enumerate(pairs)]]
                    ))
    return opts

# Init with [(symbol,label,value,)...((symbol,label,value)]
def createValuedOpts(name,triplets):
    optsclass=namedtuple(name+'Type',[symbol for symbol,_,_ in triplets]+['labels','labelTuples','values'])
    opts=optsclass(*(
                    range(len(triplets))
                    +[[label for _,label,_ in triplets]]
                    +[[(label,i) for i,(_,label,_) in enumerate(triplets)]]
                    +[[value for _,_,value in triplets]]
                    ))
    return opts

# To set the text on the target path, each character is given a "pivot point".
# This point is the point to be moved to the target path, as well as the center
# of rotation to adjust the character tilt. The X coordinate of the pivot point
# is always the middle of the character box (single-character text layer). 
# The Y coordinate is  the combination of an adjustment value, and one of the 
# following heights:

Pivot=createOpts('Pivot',
    [
    ('BASELINE',  'Baseline'),                      # The baseline
    ('TOP',       'Top of box'),                    # The top of the character box    
    ('BOTTOM',    'Bottom of box'),                 # The bottom of the character box
    ('BOXMIDDLE', 'Middle of box'),                 # The middle of the character box
    ('UCTOP',     'Top of uppercase'),              # The top of uppercase characters
    ('UCMIDDLE',  'Middle of uppercase'),           # The middle of uppercase characters
    ('LCTOP',     'Top of lowercase'),              # The top of "regular" lowercase characters
    ('LCMIDDLE',  'Middle of lowercase'),           # The middle of "regular" lowercase characters
    ])

# Characters that won't produce a path (space, etc...)
blankCharacters=' '

# Text formatting over the path. 
# CENTER/LEFT/RIGHT will use the defined extra spacing
# JUSTIFY/REPEAT compute an extra spacing to fit the stroke width
Layout=createOpts('Layout',
                    [('LEFT','Left'),('RIGHT','Right'),('CENTER','Center'),
                    ('JUSTIFY','Justify'),('REPEAT','Repeat')])

def dumpPath(path):
    for stroke in path.strokes:
        print '---'
        points,closed=stroke.points
        for i in range(0,len(points),6):
            print '***%7.2f,%7.2f <--- %7.2f,%7.2f ---> %7.2f,%7.2f' % tuple((points[i:i+6]))

#----------------------------------------------------
# Enhanced path Stroke
#----------------------------------------------------
class DirectionStroke:
            
    def __init__(self,stroke,backwards):
        self.stroke=stroke
        self.backwards=backwards
        self.delta=-0.5 if self.backwards else 0.5
        self.points,self.closed=self.stroke.points
        bezierCurves=(len(self.points)/3)-1
        
        # Number of curves seems to have an influence on global
        # precision, so adapt precision to number of curves forsft  
        # best results
        self.precision=.05/bezierCurves

        # The stroke length, computed once for all. 
        # It appears that due to precision errors
        # self.stroke.get_point_at_dist(self.length) 
        # may not return a valid point.
        self.length=stroke.get_length(self.precision)

    # Obtain the oriented angle of the tangent at point. The Gimp API gives
    # an actual slope value without orientation, so we disambiguate using
    # an auxiliary point a bit farther in the stroke. This could lead to problems
    # if used too close to the end point (auxiliary point outside the stroke)
    # but we will only use this at least half a character away from the end.
    def computeOrientedSlope(self,dx,dy,slope):
        if abs(slope) >100000: # very vertical
            return math.atan2(dy,dx) # no perfect, but properly oriented
        # keep dx/dy signs but give then the same ratio as in slope
        return math.atan2(math.copysign(slope,dy),math.copysign(1,dx))
    
    # Facade method, returns only if point is OK
    def getRawPointAtDist(self,dist):
        x,y,slope,valid=self.stroke.get_point_at_dist(dist,self.precision)
        if not valid: # Normally quite unlikely, since we avoid the cases where this could happen
            raise Exception('No point found at %6.4f in stroke %s with length %6.4f' % (dist,self.stroke.ID,self.length))
        return x,y,slope
    
    # Enhanced version of stroke.get_point_at_dist(...) that returns
    # information about the path direction. A full version should be able to 
    # handle special cases (extremities or past extremities) but this one is 
    # user at half a caharcter width from the stroke extremities.
    # 
    def getPointAtDist(self,dist):
        if self.backwards:
            dist=self.length-dist
        x,y,slope=self.getRawPointAtDist(dist)
        
        # Find the direction of the curve at given point, by comparing 
        # coordinates with nearby point further along the path at an 
        # arbitrary distance delta. We assume that dist+delta is still 
        # on the curve (ie, dist no too close to end)
        toX,toY,s=self.getRawPointAtDist(dist+self.delta) 
        theta=self.computeOrientedSlope(toX-x,toY-y,slope)
        #trace("D: %3.2f -> %3.2f, %3.2f @%3.2f°" % (dist,x,y,theta*180/math.pi)) 
        return (x,y,theta)

#---------------------------------------------------------------------------
# PathCollectors
#
# These objects accumulate the paths produced when laying out the characters.
# 
# They are implemented as Python context managers, context exit triggering
# the actual addition of the paths to the image (otherwise they are discarded)
#---------------------------------------------------------------------------

class PathCollector(object):
    def __init__(self,image,pathName,showBoxes):
        self.image=image
        self.pathName=pathName
        self.showBoxes=showBoxes
        self.paths=[]

    def __exit__(self,exc_type, exc_val, exc_tb):
        if not exc_type:  # Normal end
            trace("Path collection ended, adding %d paths" % len(self.paths))
            for p in self.paths:
                pdb.gimp_image_add_vectors(self.image,p,0)
                p.visible=True
        else:
            for p in self.paths:
                gimp.delete(p)
        return False        

    # Overloaded by the classes that use them
    def enterStroke(self,strokeIndex):
        pass;

    def enterCharacter(self,charIndex,char):
        pass;

    def copyMovePath(self,sourcePath,targetPath,cX,cY,pX,pY,tilt):
        offsets=itertools.cycle([cX,cY])
        for sourceStroke in sourcePath.strokes:
            # Workaround because Gimp's own Stroke.translate() isn't usable here since it
            # truncates the offsets to integer values. So, after rotating the stroke, we
            # get the points, translate the points, and add them back as a new stroke.
            points,closed=sourceStroke.points
            translated=[coord+next(offsets) for coord in points]
            copiedStroke = gimp.VectorsBezierStroke(targetPath,translated,closed)
            copiedStroke.rotate(cX+pX,cY+pY,tilt)

class OnePathToRuleThemAll(PathCollector):
    def __init__(self,image,pathName,showBoxes):
        super(OnePathToRuleThemAll,self).__init__(image,pathName,showBoxes)
        self.path=None
        self.boxesPath=None
        
    def __enter__(self):
        self.path=gimp.Vectors(self.image,self.pathName)
        self.paths.append(self.path)
        if self.showBoxes:
            self.boxesPath=gimp.Vectors(self.image,'Boxes for '+self.pathName) 
            self.paths.append(self.boxesPath)        

    def addCharacter(self,cPath,cX,cY,pX,pY,tilt,cType):
        self.copyMovePath(cPath,self.path,cX,cY,pX,pY,tilt)

    def addBox(self,bPath,cX,cY,pX,pY,tilt,cType):
        if self.showBoxes:
            self.copyMovePath(bPath,self.boxesPath,cX,cY,pX,pY,tilt)

class OnePathPerStroke(PathCollector):
    def __init__(self,image,pathName,showBoxes):
        super(OnePathPerStroke,self).__init__(image,pathName,showBoxes)
        self.path=None
        self.boxesPath=None
        
    def __enter__(self):
        pass;

    def enterStroke(self,strokeIndex):
        self.path=gimp.Vectors(self.image,'%s[%02d]' % (self.pathName,strokeIndex))
        self.paths.append(self.path)
        if self.showBoxes:
            self.boxesPath=gimp.Vectors(self.image,'Boxes for %s[%02d]' % (self.pathName,strokeIndex)) 
            self.paths.append(self.boxesPath)        

    def addCharacter(self,cPath,cX,cY,pX,pY,tilt,cType):
        self.copyMovePath(cPath,self.path,cX,cY,pX,pY,tilt)

    def addBox(self,bPath,cX,cY,pX,pY,tilt,cType):
        if self.showBoxes:
            self.copyMovePath(bPath,self.boxesPath,cX,cY,pX,pY,tilt)

class TextAndSpacer(PathCollector):
    def __init__(self,image,pathName,showBoxes):
        super(TextAndSpacer,self).__init__(image,pathName,showBoxes)
        self.path=None
        self.boxesPath=None
        
    def __enter__(self):
        textPath=gimp.Vectors(self.image,'Text for %s' %   self.pathName) 
        joinPath=gimp.Vectors(self.image,'Spacer for %s' % self.pathName) 
        self.cPaths=[textPath,joinPath]
        self.paths.extend(self.cPaths)
        if self.showBoxes:
            textPath=gimp.Vectors(self.image,'Text boxes for %s' %   self.pathName) 
            joinPath=gimp.Vectors(self.image,'Spacer boxes for %s' % self.pathName) 
            self.bPaths=[textPath,joinPath]
            self.paths.extend(self.bPaths)

    def addCharacter(self,cPath,cX,cY,pX,pY,tilt,cType):
        self.copyMovePath(cPath,self.cPaths[cType],cX,cY,pX,pY,tilt)

    def addBox(self,bPath,cX,cY,pX,pY,tilt,cType):
        if self.showBoxes:
            self.copyMovePath(bPath,self.bPaths[cType],cX,cY,pX,pY,tilt)

class EachOnItsOwn(PathCollector):
    def __init__(self,image,pathName,showBoxes):
        super(EachOnItsOwn,self).__init__(image,pathName,showBoxes)
        
    def __enter__(self):
        pass;

    def enterStroke(self,strokeIndex):
        self.strokeName='%s[%02d]' % (self.pathName,strokeIndex)

    def enterCharacter(self,charIndex,char):
        self.charPath=gimp.Vectors(self.image,'%s[%02d][%s]' % (self.strokeName,charIndex,char))
        self.paths.append(self.charPath)

    def addCharacter(self,cPath,cX,cY,pX,pY,tilt,cType):
        self.copyMovePath(cPath,self.charPath,cX,cY,pX,pY,tilt)

    def addBox(self,bPath,cX,cY,pX,pY,tilt,cType):
        if self.showBoxes:
            self.copyMovePath(bPath,self.charPath,cX,cY,pX,pY,tilt)

pathCollectorTypes= [OnePathToRuleThemAll,OnePathPerStroke,      TextAndSpacer,                   EachOnItsOwn]
pathCollectorLabels=["One single path",   "One path per stroke", "Separate text and spacer paths","One path per character"]

#----------------------------------------------------
# Character in text
#----------------------------------------------------
CTYPE_TEXT=0
CTYPE_JOIN=1

class Character(object):
    def __init__(self,character,width,height,ctype):
        self.character=character
        self.width=width
        self.height=height
        self.path=None
        self.boxPath=None
        self.marginL=0
        self.marginR=0
        self.kerning=0 # Normally negative when characters are squeezed (AV, XO)
        self.position=0
        self.ctype=ctype
        
    def __str__(self):
        if self.path:
            return "<'%s' (%d,%d) @%3.2f, [%s], %d stroke(s)>" % (self.character,self.width,self.height,self.position,"TS"[self.ctype],len(self.path.strokes))
        else:
            return "<'%s' (%d,%d) @%3.2f, [%s], (no path)>" % (self.character,self.width,self.height,self.position,"TS"[self.ctype])
    
    def __repr__(self):
        return str(self)
    
    def dumpPath(self):
        if self.path:
           dumpPath(self.path)

#----------------------------------------------------
# Text to work on
#----------------------------------------------------
class Formatter(object):
    
    def __init__(self,text,joiner,fontName,fontSize,
            layout=Layout.CENTER, useKerning=True, extraSpacing=0,
            pivotYChoice=Pivot.BASELINE, verticalAdjust=0,
            keepUpright=False,wiggleXPercent=0, wiggleYPercent=0, wiggleTheta=0):
        self.text=list(unicode(text,'utf-8','strict'))
        self.joiner=list(unicode(joiner,'utf-8','strict'))
        self.fontName=fontName
        self.fontSize=fontSize
        self.layout=layout
        self.useKerning=useKerning
        self.extraSpacing=extraSpacing
        self.pivotYChoice=pivotYChoice
        self.verticalAdjust=verticalAdjust
        self.keepUpright=keepUpright
        self.wiggleXPercent=wiggleXPercent
        self.wiggleYPercent=wiggleYPercent
        self.wiggleTheta=wiggleTheta
        
        self.pivotY=None
        self.textCharacters=[]
        self.joinCharacters=[]
        self.workImage=gimp.Image(int(fontSize*4),int(fontSize*4), RGB)
        self.workImage.disable_undo()
        self.computePivotY()
        self.initializeCharacters()
        
    def __del__(self):
        gimp.delete(self.workImage)

    def extents(self,text):
        ext = pdb.gimp_text_get_extents_fontname(text, self.fontSize, PIXELS, self.fontName)
        #trace("extents[w](%s)=%3.2f" % (text,ext[0]))
        return ext
        
    def boxPath(self,w,h):
        w,h=float(w),float(h)
        path=gimp.Vectors(self.workImage,'**')
        points=[0.,0.]*3+[w,0.]*3+[w,h]*3+[0.,h]*3
        gimp.VectorsBezierStroke(path,points,True)
        return path
        
    def textPath(self,text):
        l=pdb.gimp_text_fontname(self.workImage, None, 0, 0, text, 0, True, self.fontSize, PIXELS, self.fontName)
        path=pdb.gimp_vectors_new_from_text_layer(self.workImage,l)
        self.workImage.remove_layer(l)
        return path
        
    def createCharacter(self,c,k,ctype):
        cw,ch,_,_=self.extents(c)
        char=Character(c,cw,ch,ctype)
        if c not in blankCharacters:
            char.path=self.textPath(c)
            char.boxPath=self.boxPath(cw,ch)
            # compute margins
            allX=[x for stroke in char.path.strokes for x in stroke.points[0][0::2]]
            char.marginL=min(allX)
            char.marginR=cw-max(allX)
        
        # compute kerning if necessary
        if k and self.useKerning:
            kw,_,_,_=self.extents(k)
            pw,_,_,_=self.extents(k+c)
            # Kerning is the difference between width of the pair with kerning (pw) 
            # and the sum of the individual character widths (can be negative: "AV")
            char.kerning=pw-(cw+kw)
            trace('Kerning %c -> %c: %3.2f - (%3.2f + %3.2f) = %3.2f' % (k,c,pw,cw,kw,char.kerning))
        return char
    
    def initializeCharacters(self):
        trace('Text: %s, Joiner: %s' % (''.join(self.text),''.join(self.joiner)))
        # To compute kerning a character needs to know the character on its right
        # For the first character of the text this is the last character of the text or the joiner
        # Kerning for 1st character is always computed even if its not used on open strokes
        firstKerning=self.joiner[-1] if self.joiner and self.layout==Layout.REPEAT else self.text[-1]            
        kerningCharacters=[firstKerning]+self.text[:-1]
        self.textCharacters=[self.createCharacter(c,k,CTYPE_TEXT) for c,k in zip(self.text,kerningCharacters)]
        
        if self.joiner:
        # For the first character of the joiner this is the last character of the text
            firstKerning=self.text[-1]   
            kerningCharacters=[firstKerning]+self.joiner[:-1]
            self.joinCharacters=[self.createCharacter(c,k,CTYPE_JOIN) for c,k in zip(self.joiner,kerningCharacters)]
                        
    # Compute offsets for pivot point Y. Since there is no API to obtain geometry information
    # for the font, some guesswork is required. We will assume that 'X' and 'x' are fairly symmetrical
    # and that their topmost point is as much above the line of upper/lowercase tops than their lowest point
    # is below the baseline (except for very round fonts this will be 0).
    
    def verticalSpread(self,text,ascent):
        # Obtain path for sample text
        path=self.textPath(text)
        # Gather all Y values (anchors and handles) in all strokes for the bounding box 
        allY=[y for stroke in path.strokes for y in stroke.points[0][1::2]] 
        gimp.delete(path)
        minY=min(allY)
        maxY=max(allY)
        top=minY+(maxY-ascent)
        middle=(minY+maxY)/2.
        return top,middle
    
    def computePivotY(self):
        
        width,height,ascent,descent=self.extents('X')
        trace(
'''
==================
Width:     %7.2f
Height:    %7.2f
Ascent:    %7.2f
Descent:   %7.2f
------------------
''' % (width,height,ascent,descent))
        self.wiggleYMax=height
    
        # compute all possible pivotY and keep the good one (easier to debug)
        pivot=[0 for _ in Pivot.labels] # Array of same size as choices
        pivot[Pivot.BASELINE]=ascent
        pivot[Pivot.TOP]=0
        pivot[Pivot.BOTTOM]=height
        pivot[Pivot.BOXMIDDLE]=height/2.
        pivot[Pivot.UCTOP],pivot[Pivot.UCMIDDLE]=self.verticalSpread('X',ascent)
        pivot[Pivot.LCTOP],pivot[Pivot.LCMIDDLE]=self.verticalSpread('x',ascent)
        
        trace(
'''
Baseline:  %7.2f
Top:       %7.2f
Bottom:    %7.2f
MiddleBox: %7.2f
TopUC:     %7.2f
MiddleUC:  %7.2f
TopLC:     %7.2f
MiddleLC:  %7.2f
''' % tuple(pivot))
        self.pivotY=pivot[self.pivotYChoice]+self.verticalAdjust

    # Functions to compute how to layout the characters on the stroke 
    # Return:
    #  - actual character sequence
    #  - actual extra spacing
    #  - total string width
    
    def checkFit(self,textWidth,strokeLength):
         if textWidth > strokeLength:
            raise Exception('Text width (%3.2f) larger than path stroke length (%3.2f)' % (textWidth,strokeLength))
        
    def firstTextWidth(self,characters):
        rawTextWidth=sum([c.width+c.kerning for c in characters])
        rawTextWidth-=characters[0].kerning # No kerning on 1st
        rawTextWidth-=characters[0].marginL+characters[-1].marginR # Exclude margins
        return rawTextWidth

    def plainTextWidth(self,characters):
        rawTextWidth=self.firstTextWidth(characters)
        intervals=len(characters)-1
        textWidth=rawTextWidth+self.extraSpacing*intervals
        return textWidth

    # LEFT, RIGHT, CENTERED
    # Just check fit on stroke, kerning of 1st char is not used

    def layoutLeft(self,stroke):
        textWidth=self.plainTextWidth(self.textCharacters)
        self.checkFit(textWidth,stroke.length)
        # compensate for left margin if necessary
        offset=-self.textCharacters[0].marginL
        return self.textCharacters,self.extraSpacing,textWidth,offset
        
    def layoutRight(self,stroke):
        textWidth=self.plainTextWidth(self.textCharacters)
        self.checkFit(textWidth,stroke.length)
        # compensate for right margin if necessary
        offset=stroke.length-(textWidth+self.textCharacters[0].marginL)
        return self.textCharacters,self.extraSpacing,textWidth,offset

    def layoutCenter(self,stroke):
        textWidth=self.plainTextWidth(self.textCharacters)
        self.checkFit(textWidth,stroke.length)
        offset=((stroke.length-textWidth)/2.)-self.textCharacters[0].marginL
        return self.textCharacters,self.extraSpacing,textWidth,offset

    # FILLED
    def layoutFilled(self,stroke):
        # String always fits even if it requires to collapse everything.
        # Might creash is path shorter that one character width
        if stroke.closed:
            # last char abutted on first, so kerning counts and #intervals=#chars
            # However the margins are always used (all characters have neighbors on both sides)
            textWidth=sum([c.width+c.kerning for c in self.textCharacters])
            intervals=len(self.textCharacters)
        else:
            # no kerning on 1st, and one less intervals, consider margins
            textWidth=self.plainTextWidth(self.textCharacters)
            intervals=len(self.textCharacters)-1
        offset=-self.textCharacters[0].marginL
        return self.textCharacters,(stroke.length-textWidth)/intervals,stroke.length,offset
        
    # REPEATED
    def layoutRepeated(self,stroke):
        if stroke.closed:
            return self.layoutRepeatedOnClosed(stroke)
        else:
            return self.layoutRepeatedOnOpen(stroke)
        
    def layoutRepeatedOnClosed(self,stroke):
        # joiner always used
        # kerning on 1st included, margins included
        textUnit=self.textCharacters+self.joinCharacters
        rawTextUnitWidth=sum([c.width+c.kerning for c in textUnit])
        textUnitWidth=rawTextUnitWidth+(self.extraSpacing*len(textUnit))
        # Check we can at least fit one
        self.checkFit(textUnitWidth,stroke.length)
        repeat=int(stroke.length/textUnitWidth)
        # deep copy needed because we update each character with its position
        actualTextCharacters=[copy.copy(c) for _ in range(repeat) for c in textUnit]
        rawFullTextLength=rawTextUnitWidth*repeat
        actualSpacing=(stroke.length-rawFullTextLength)/len(actualTextCharacters)
        trace("Stroke: %3.2f, Unit: %3.2f, Repeat: %d, Full: %3.2f, actualSpacing: %3.2f" %
               (stroke.length,textUnitWidth,repeat,rawFullTextLength,actualSpacing))
        offset=-textUnit[0].marginL
        return actualTextCharacters, actualSpacing,stroke.length,offset
        
    def layoutRepeatedOnOpen(self,stroke):
        # joiner not used if we can only fit one copy
        textFirstUnit=self.textCharacters
        rawTextFirstUnitWidth=self.firstTextWidth(textFirstUnit)
        textFirstUnitWidth=rawTextFirstUnitWidth+(self.extraSpacing*(len(textFirstUnit)-1))
        # Check we can at least fit one
        self.checkFit(textFirstUnitWidth,stroke.length)
        # Addional repeats: always joiner+text, first character has kerning
        # And as many intervals as characters
        textMoreUnit=self.joinCharacters+self.textCharacters
        rawTextMoreUnitWidth=sum([c.width+c.kerning for c in textMoreUnit])
        textMoreUnitWidth=rawTextMoreUnitWidth+(self.extraSpacing*len(textMoreUnit))
        repeat=int((stroke.length-textFirstUnitWidth)/textMoreUnitWidth)
        # deep copy needed because we update each character with its position
        actualTextCharacters=[copy.copy(c) for c in textFirstUnit]+[copy.copy(c) for _ in range(repeat) for c in textMoreUnit]
        rawFullTextLength=rawTextFirstUnitWidth+(rawTextMoreUnitWidth*repeat)
        actualSpacing=(stroke.length-rawFullTextLength)/(len(actualTextCharacters)-1) 
        trace("Stroke: %3.2f, First: %3.2f, More: %3.2f, Repeat: %d, Full: %3.2f, actualSpacing: %3.2f" %
               (stroke.length,textFirstUnitWidth,textMoreUnitWidth,repeat,rawFullTextLength,actualSpacing))
        offset=-textFirstUnit[0].marginL
        return actualTextCharacters, actualSpacing,stroke.length,offset

    # Lay out the characters on the stroke, by computing their.position coordinate
    def layoutOnStroke(self,stroke):
        layoutFunction=[self.layoutLeft,self.layoutRight,self.layoutCenter,self.layoutFilled,self.layoutRepeated]
        self.actualCharacters,actualSpacing,textWidth,offset=layoutFunction[self.layout](stroke)
            
        self.wiggleXMax=textWidth/len(self.actualCharacters)
        
        trace('Stroke length: %3.2f, start offset: %3.2f, actualSpacing: %3.2f, actual text width: %3.2f ' % (stroke.length, offset, actualSpacing, textWidth))
        
        # set position for each character (actually position of Pivot/Center of character)
        for c in self.actualCharacters:
            position=offset+c.width/2.+c.kerning
            offset=position+c.width/2.+actualSpacing
            c.position=position
            trace(c)
            
    # compute final pos for character
    def computeFinalPos(self,c,stroke):
        x,y,slope=stroke.getPointAtDist(c.position)
        if self.keepUpright:
            tilt=0
        else:
            tilt=slope*180/math.pi
        
        wiggleXRange=self.wiggleXMax*self.wiggleXPercent/100.
        wiggleYRange=self.wiggleYMax*self.wiggleYPercent/100.

        wx=random.uniform(-wiggleXRange,wiggleXRange)
        wy=random.uniform(-wiggleYRange,wiggleYRange)
        wtilt=random.uniform(-self.wiggleTheta,self.wiggleTheta)

        return x+wx*math.cos(slope)-wy*math.sin(slope),y+wy*math.cos(slope)+wx*math.sin(slope),tilt+wtilt
        
    def copyStrokes(self,sourcePath,targetPath):
        for s in sourcePath.strokes:
            points,closed=s.points
            stroke = gimp.VectorsBezierStroke(targetPath,points, closed)

    def moveCharacterToStroke(self,c,stroke,pathCollector):
        if not c.path:
            return # nothing to do on blank characters
        
        x,y,tilt=self.computeFinalPos(c,stroke)
        trace("%3.2f moved to %3.2f,%3.2f" % (c.position,x,y)) 
        
        # Position of NW corner of character box
        cX=x-c.width/2.
        cY=y-self.pivotY
        # Position of pivot in box
        pX=c.width/2.
        pY=self.pivotY
        pathCollector.addCharacter(c.path,cX,cY,pX,pY,tilt,c.ctype)
        pathCollector.addBox(c.boxPath,cX,cY,pX,pY,tilt,c.ctype)
            
    def moveCharactersToStroke(self,stroke,pathCollector):
        trace("Max wiggle X,Y: %3.2f,%3.2f" % (self.wiggleXMax,self.wiggleYMax))
        for i,c in enumerate(self.actualCharacters,1):
            pathCollector.enterCharacter(i,c.character)
            self.moveCharacterToStroke(c,stroke,pathCollector)
            
def textAlongPath(image,guidePath,
                  text,joiner,fontName,fontSize,
                  layout,useKerning,extraSpacing,pivotYChoice,verticalAdjust,
                  keepUpright,wiggleXPercent,wiggleYPercent,wiggleTheta,
                  backwards,generationType,showBoxes):
    
    pdb.gimp_image_undo_group_start(image)
    try:
        if not fontName:
            fontName = pdb.gimp_context_get_font()
        if not text:
            raise Exception('No text provided')
        if not len(guidePath.strokes):
            raise Exception('No strokes in path "%s"' % guidePath.name)
        if joiner:
            pathName="'%s' + '%s' over <%s>" % (text,joiner,guidePath.name)
        else:
            pathName="'%s' over <%s>" % (text,guidePath.name)
        pathCollector=pathCollectorTypes[generationType](image,pathName,showBoxes)
        formatter=Formatter(text,joiner,fontName,fontSize,
                layout,useKerning,extraSpacing,pivotYChoice,verticalAdjust,
                keepUpright,wiggleXPercent,wiggleYPercent,wiggleTheta)
        with pathCollector:
            for i,s in enumerate(guidePath.strokes,1):
                stroke=DirectionStroke(s,backwards)
                pathCollector.enterStroke(i)
                formatter.layoutOnStroke(stroke)
                formatter.moveCharactersToStroke(stroke,pathCollector)
    except Exception as e:
        trace(e.args[0])
        if debug:
            traceback.print_exc()
        pdb.gimp_message(e.args[0])
    pdb.gimp_image_undo_group_end(image)
    
def textAlongPathMulti(image,guidePath,
                  texts,joiner,fontName,fontSize,
                  layout,useKerning,extraSpacing,pivotYChoice,verticalAdjust,
                  keepUpright,wiggleXPercent,wiggleYPercent,wiggleTheta,
                  backwards,generationType,showBoxes):
    
    pdb.gimp_image_undo_group_start(image)
    try:
        if not fontName:
            fontName = pdb.gimp_context_get_font()
        if not texts:
            raise Exception('No text provided')
        texts=[t for t in texts.translate(None,'\r').split('\n') if len(t) > 0]
        if len(guidePath.strokes) != len(texts):
            raise Exception('Number of strokes in path "%s" (%d) does not match the number of lines of text (%d)' % (guidePath.name,len(guidePath.strokes),len(texts)))
        if joiner:
            pathName="'%s' + '%s' over <%s>" % ('<multiple>',joiner,guidePath.name)
        else:
            pathName="'%s' over <%s>" % ('<multiple>',guidePath.name)
        pathCollector=pathCollectorTypes[generationType](image,pathName,showBoxes)
        with pathCollector:
            for i,(s,text) in enumerate(zip(guidePath.strokes,texts),1):
                formatter=Formatter(text,joiner,fontName,fontSize,
                        layout,useKerning,extraSpacing,pivotYChoice,verticalAdjust,
                        keepUpright,wiggleXPercent,wiggleYPercent,wiggleTheta)
                stroke=DirectionStroke(s,backwards)
                pathCollector.enterStroke(i)
                formatter.layoutOnStroke(stroke)
                formatter.moveCharactersToStroke(stroke,pathCollector)
    except Exception as e:
        trace(e.args[0])
        if debug:
            traceback.print_exc()
        pdb.gimp_message(e.args[0])
    pdb.gimp_image_undo_group_end(image)

### Registration

whoiam='\n'+os.path.abspath(__file__)
defaultFontName='Sans'
defaultFontSize=20
fontEnv=os.getenv('OFN_TEXT_ALONG_PATH_FONT')
if fontEnv:
    defaultFontName,defaultFontSize=fontEnv.split(':');
    defaultFontSize=int(defaultFontSize)

# Registration items

regImage=           (PF_IMAGE,   'image',           'Input image:',             None)
regPath=            (PF_VECTORS, 'path',            'Guide path:',              None)
regText=            (PF_STRING,  'text',            'Text:',                    '')
regMultiText=       (PF_TEXT,    'text',            'Text:',                    '')
regJoiner=          (PF_STRING,  'joiner',          'Spacer:',                  '')
regFontName=        (PF_FONT,    'fontName',        'Font name:',               defaultFontName)
regFontSize=        (PF_SPINNER, 'fontSize',        'Font size:',               defaultFontSize,(1, 1000, 1))
regLayout=          (PF_OPTION,  'layout',          'Layout:',                  Layout.CENTER,Layout.labels)
regUseKerning=      (PF_TOGGLE,  'useKerning',      'Use kerning:',             True)
regExtraSpacing=    (PF_FLOAT,   'extraSpacing',    'Extra spacing (px):',      0.)
regHeightReference= (PF_OPTION,  'pivotYChoice',    'Height reference:',        Pivot.BASELINE,Pivot.labels)
regVerticalAdjust=  (PF_FLOAT,   'verticalAdjust',  'Vertical adjust (px):',    0.)
regKeepUpright=     (PF_TOGGLE,  'keepUpright',     'Keep upright:',            False)
regWiggleXPercent=  (PF_SPINNER, 'wiggleXPercent',  'Lateral wiggle (%):',      0,(0, 100, 1))
regWiggleYPercent=  (PF_SPINNER, 'wiggleYPercent',  'Vertical wiggle (%):',     0,(0, 100, 1))
regWiggleTheta=     (PF_SPINNER, 'wiggleTheta',     'Tilt wiggle (°):',         0,(0, 90, 1))
regBackwards=       (PF_TOGGLE,  'backwards',       'Reverse stroke direction:',False)
regPathGeneration=  (PF_OPTION,  'generationType',  'Generate:',                0,pathCollectorLabels)
regShowBoxes=       (PF_TOGGLE,  'showBoxes',       'Show boxes as paths:',     False)

register(
    'ofn-text-along-path',
    'Text along path...'+whoiam,
    'Text along path...',
    'Ofnuts',
    'Ofnuts',
    '2017',
    'Text along path...',
    '*',
    [
        regImage,
        regPath,
        regText,
        regJoiner,
        regFontName,
        regFontSize,
        regLayout,
        regUseKerning,
        regExtraSpacing,
        regHeightReference,
        regVerticalAdjust,
        regKeepUpright,
        regWiggleXPercent,
        regWiggleYPercent,
        regWiggleTheta,
        regBackwards,
        regPathGeneration,
        regShowBoxes
    ],
    [],
    textAlongPath,
    menu='<Vectors>/Tools',
)
        
register(
    'ofn-text-along-path-multi',
    'Text (multi) along path...'+whoiam,
    'Text (multi) along path...',
    'Ofnuts',
    'Ofnuts',
    '2017',
    'Text (multi) along path...',
    '*',
    [
        regImage,
        regPath,
        regMultiText,
        regJoiner,
        regFontName,
        regFontSize,
        regLayout,
        regUseKerning,
        regExtraSpacing,
        regHeightReference,
        regVerticalAdjust,
        regKeepUpright,
        regWiggleXPercent,
        regWiggleYPercent,
        regWiggleTheta,
        regBackwards,
        regPathGeneration,
        regShowBoxes
    ],
    [],
    textAlongPathMulti,
    menu='<Vectors>/Tools',
)
        
main()
