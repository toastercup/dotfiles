# Note to self regarding use of .zsh* files:
# http://unix.stackexchange.com/a/71258

source /usr/share/zsh/scripts/antigen/antigen.zsh
antigen use oh-my-zsh
antigen bundle command-not-found
antigen bundle zsh-users/zsh-syntax-highlighting
antigen bundle Tarrasch/zsh-autoenv
antigen bundle alexrochas/zsh-git-semantic-commits
antigen apply
