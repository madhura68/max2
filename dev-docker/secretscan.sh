#!/usr/bin/env bash
nopw=0; [ "$1" = --no-password ] && { nopw=1; shift; }
[ -n "$1" ] || { echo "gebruik: secretscan.sh [--no-password] '<commitbericht>'"; exit 2; }
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)" || exit 1                # afwijking 6: repo-root uit de scriptlocatie (worktree-veilig)
[ "$(git branch --show-current)" = feat/dev-docker-host ] || { echo FOUT-branch; exit 1; }
set -o pipefail
git add -A evidence/dev-docker                                                         # plus eventuele andere bedoelde bestanden
git grep -qE --cached 'postgres(ql)?://dev:[^*]' -- . ':!*.md'; rc=$?
[ "$rc" -eq 1 ] || { echo "FOUT-url rc=$rc"; git grep -lE --cached 'postgres(ql)?://dev:[^*]' -- . ':!*.md'; exit 1; }
git grep -qE --cached '//dev:[^*]' -- evidence/dev-docker; rc=$?
[ "$rc" -eq 1 ] || { echo "FOUT-url rc=$rc"; git grep -lE --cached '//dev:[^*]' -- evidence/dev-docker; exit 1; }
if [ "$nopw" = 0 ]; then                                                               # taak 1: --no-password (nog geen wachtwoord)
pw=$(docker --context max2-dev exec dev-postgres printenv DEV_PASSWORD) || { echo FOUT-ophaal; exit 1; }
[ -n "$pw" ] || { echo FOUT-leeg; exit 1; }
git diff --cached --name-only -z --diff-filter=d | MASK_RAW="$pw" perl -e '
  $/ = "\0"; my $p = $ENV{MASK_RAW}; my ($n, $hit) = (0, 0);
  while (my $f = <STDIN>) { chomp $f; $n++;
    open(my $h, "-|", "git", "show", ":$f") or do { print STDERR "FOUT-lees $f\n"; exit 2 };
    my $c = do { local $/; <$h> }; close($h) or do { print STDERR "FOUT-lees $f\n"; exit 2 };
    if (index($c, $p) >= 0) { $hit = 1; print "LEK $f\n" } }
  if (!$n) { print STDERR "FOUT-geen-bestanden\n"; exit 2 }
  print "schoon\n" unless $hit; exit $hit'
rc=$?; unset pw
[ "$rc" -eq 0 ] || { echo "niet committen (rc=$rc)"; exit "$rc"; }
fi
git commit -m "$1"                                                                     # zonder -a; daarna push
