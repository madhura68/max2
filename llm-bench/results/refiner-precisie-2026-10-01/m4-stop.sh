#!/bin/bash
d=$(mktemp -d)
q="select id, kind, status, retry_count from claude_jobs where required_capability = 'local_llm' order by id"
opname() {   # $1 = voor | na; een opname telt alleen bij exitcode 0 van psql
  ssh scrum4me-srv "docker exec -i scrum4me-postgres psql -U scrum4me -d scrum4me -Atc \"$q\"" > "$d/$1.tmp" &&
    mv "$d/$1.tmp" "$d/$1.txt"
}
opname voor || { echo "opname voor mislukt: niet stoppen"; exit 1; }
grep -qE '\|(CLAIMED|RUNNING)\|' "$d/voor.txt"
case $? in
  0) echo "local_llm-job geclaimd of bezig: niet stoppen"; exit 1 ;;
  1) ;;
  *) echo "controle op claims mislukt: niet stoppen, JP"; exit 1 ;;
esac
ssh max2 'sudo -n systemctl stop agent-harness-worker' || { echo "stop mislukt: JP"; exit 1; }
toestand=$(ssh max2 'systemctl is-active agent-harness-worker')
case "$toestand" in inactive|failed) ;; *) echo "worker is $toestand na de stop: JP"; exit 1 ;; esac
opname na || { echo "opname na mislukt: worker blijft gestopt, JP"; exit 1; }
diff "$d/voor.txt" "$d/na.txt"
case $? in
  0) echo "schone stop" ;;
  1) echo "verschil: worker blijft gestopt, de ID's uit de diff naar JP (M4 stap 2)"; exit 1 ;;
  *) echo "diff mislukt: worker blijft gestopt, JP"; exit 1 ;;
esac
