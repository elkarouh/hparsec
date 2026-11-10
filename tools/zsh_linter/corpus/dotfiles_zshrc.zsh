# ~/.zshrc — interactive shell configuration
# Loaded for every interactive zsh session.

export EDITOR="${EDITOR:-nvim}"
export PAGER=less
export LESS="-R -F -X"
export GPG_TTY=$(tty)

typeset -U path PATH
path=(
  $HOME/.local/bin
  $HOME/go/bin
  /usr/local/bin
  $path
)
export PATH

HISTFILE=${XDG_STATE_HOME:-$HOME/.local/state}/zsh/history
HISTSIZE=50000
SAVEHIST=$HISTSIZE
mkdir -p "${HISTFILE:h}"

setopt APPEND_HISTORY HIST_IGNORE_ALL_DUPS HIST_REDUCE_BLANKS
setopt INTERACTIVE_COMMENTS NO_BEEP PROMPT_SUBST

autoload -Uz compinit
if [[ -n ${HOME}/.zcompdump(#qN.mh+24) ]]; then
  compinit
else
  compinit -C
fi

zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Za-z}'
zstyle ':completion:*:descriptions' format '%F{yellow}-- %d --%f'

bindkey -e
bindkey '^[[A' history-substring-search-up
bindkey '^[[B' history-substring-search-down

alias ll='ls -lah --color=auto'
alias gs='git status -sb'
alias ..='cd ..'

if (( $+commands[eza] )); then
  alias ls='eza --group-directories-first'
fi

if [[ -r "$HOME/.secrets" ]]; then
  source "$HOME/.secrets"
fi

[[ -f ~/.fzf.zsh ]] && source ~/.fzf.zsh

if command -v direnv >/dev/null 2>&1; then
  eval "$(direnv hook zsh)"
fi

for f in "$HOME"/.zsh/conf.d/*.zsh(N); do
  source "$f"
done
unset f
