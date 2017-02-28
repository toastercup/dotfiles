eval "$(rbenv init -)"

source /usr/share/zsh/share/antigen.zsh

antigen use oh-my-zsh

antigen bundle git
antigen bundle rbenv
antigen bundle ruby
antigen bundle command-not-found

antigen bundle zsh-users/zsh-syntax-highlighting
antigen bundle Tarrasch/zsh-autoenv
antigen bundle alexrochas/git-semantic-commits

antigen theme kphoen

antigen apply

