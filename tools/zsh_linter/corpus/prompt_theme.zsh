# prompt_theme.zsh — a two-line prompt with git status and exit codes.

autoload -Uz add-zsh-hook vcs_info

zstyle ':vcs_info:*' enable git
zstyle ':vcs_info:git:*' formats ' %F{magenta}(%b)%f'
zstyle ':vcs_info:git:*' actionformats ' %F{magenta}(%b|%a)%f'

typeset -gA PROMPT_COLORS=(
  [user]=green
  [path]=cyan
  [error]=red
)

typeset -g _last_exit=0
typeset -g _cmd_start=0

_prompt_precmd() {
  _last_exit=$?
  vcs_info
  if (( _cmd_start > 0 )); then
    local elapsed=$(( EPOCHSECONDS - _cmd_start ))
    (( elapsed >= 2 )) && RPROMPT="%F{yellow}${elapsed}s%f"
  else
    RPROMPT=
  fi
  _cmd_start=0
}

_prompt_preexec() {
  _cmd_start=$EPOCHSECONDS
  if [[ $1 == git\ push* ]]; then
    print -P "%F{yellow}pushing…%f"
  fi
}

add-zsh-hook precmd _prompt_precmd
add-zsh-hook preexec _prompt_preexec

PROMPT='%(?.%F{green}.%F{red})❯%f '
PROMPT='%F{$PROMPT_COLORS[path]}%~%f${vcs_info_msg_0_} %F{$PROMPT_COLORS[user]}%n%f
%(?..%F{red}[${_last_exit}]%f )%# '
