#!/usr/bin/env zsh
# deploy.zsh — build and ship the service to one or more environments.
#
# Usage: deploy.zsh [-n] [-v] env [env...]

set -eu
setopt PIPE_FAIL

typeset -r SCRIPT_NAME=${0:t}
typeset -r REGISTRY="registry.example.com/platform"
typeset -i DRY_RUN=0 VERBOSE=0
typeset -a ENVIRONMENTS
typeset -A IMAGE_TAGS

log() {
  local level=$1; shift
  print -P "%F{blue}[$(date +%H:%M:%S)]%f ${level}: $*" >&2
}

die() {
  log ERROR "$@"
  exit 1
}

run() {
  if (( DRY_RUN )); then
    log DRY "$*"
    return 0
  fi
  (( VERBOSE )) && log RUN "$*"
  "$@"
}

usage() {
  cat <<USAGE
Usage: $SCRIPT_NAME [-n] [-v] env [env...]

  -n   dry run, print the commands only
  -v   print each command before running it
USAGE
}

parse_args() {
  local opt
  while getopts ":nvh" opt; do
    case $opt in
      n) DRY_RUN=1 ;;
      v) VERBOSE=1 ;;
      h) usage; exit 0 ;;
      *) die "unknown option: -$OPTARG" ;;
    esac
  done
  shift $((OPTIND - 1))
  (( $# > 0 )) || { usage >&2; exit 2; }
  ENVIRONMENTS=("$@")
}

check_prereqs() {
  local tool
  for tool in docker kubectl git; do
    (( $+commands[$tool] )) || die "missing required tool: $tool"
  done
  if [[ -n $(git status --porcelain) ]]; then
    die "working tree is dirty; commit or stash first"
  fi
}

build_image() {
  local sha=$(git rev-parse --short HEAD)
  local image="$REGISTRY:$sha"
  log BUILD "$image"
  run docker build --pull --tag "$image" --build-arg GIT_SHA="$sha" .
  run docker push "$image"
  IMAGE_TAGS[$1]=$image
}

rollout() {
  local env=$1 image=$2
  case "$env" in
    prod|production)
      [[ -t 0 ]] && { read -q "REPLY?Deploy $image to PRODUCTION? [y/N] " || die "aborted"; echo; }
      ;;
    staging|dev) ;;
    *) die "unknown environment: $env" ;;
  esac

  run kubectl --context "$env" set image deployment/api api="$image"
  run kubectl --context "$env" rollout status deployment/api --timeout=5m
}

cleanup() {
  local rc=$?
  [[ -n ${TMP_DIR:-} && -d $TMP_DIR ]] && rm -rf -- "$TMP_DIR"
  exit $rc
}
trap cleanup EXIT INT TERM

main() {
  parse_args "$@"
  check_prereqs
  TMP_DIR=$(mktemp -d)

  build_image "${ENVIRONMENTS[1]}"

  local env
  for env in "${ENVIRONMENTS[@]}"; do
    rollout "$env" "${IMAGE_TAGS[${ENVIRONMENTS[1]}]}" || {
      log WARN "rollout to $env failed"
      continue
    }
    log OK "deployed to $env"
  done
}

main "$@"
