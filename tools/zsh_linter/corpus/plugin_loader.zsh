# plugin_loader.zsh — source plugins from a directory, tolerating missing ones.

typeset -g PLUGIN_DIR=${ZDOTDIR:-$HOME}/plugins
typeset -ga LOADED_PLUGINS=()
typeset -ga FAILED_PLUGINS=()

plugin_load() {
  local name=$1
  local dir=$PLUGIN_DIR/$name
  local init

  if [[ ! -d $dir ]]; then
    FAILED_PLUGINS+=("$name")
    return 1
  fi

  for init in "$dir/$name.plugin.zsh" "$dir/init.zsh" "$dir/$name.zsh"(N); do
    if [[ -f $init ]]; then
      source "$init" && LOADED_PLUGINS+=("$name") && return 0
    fi
  done

  FAILED_PLUGINS+=("$name")
  return 1
}

plugin_list_files() {
  local -a files
  files=( "$PLUGIN_DIR"/*/*.zsh(N.) )
  print -l -- "${(@)files:t}"
}

plugin_report() {
  if (( ${#FAILED_PLUGINS} )); then
    print -u2 "plugins failed: ${(j:, :)FAILED_PLUGINS}"
    return 1
  fi
  print "loaded ${#LOADED_PLUGINS} plugins"
}

local p
for p in git-helpers fzf-tab zsh-autosuggestions; do
  plugin_load "$p"
done
unset p

if (( $+functions[plugin_report] )); then
  plugin_report
fi
