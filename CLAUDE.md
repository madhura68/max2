# Werkinstructies — max2

## Rol van deze repo

Host-overlay voor `max2` binnen de Forgejo-Runner-tweemachinepool. De gedeelde
bundel is canoniek in de `scrum4me-server`-repo en wordt hier **niet** gekopieerd.

## Harde regels

1. **Geen secrets.** Tokens, UUID-credentials en private sleutels komen hier nooit in.
2. **Bundel niet dupliceren.** Wijzig de gedeelde bundel in `scrum4me-server` en rol
   beide hosts uit vanaf dezelfde commit-SHA. Een lokale kopie hier is drift.
3. **Eigen identiteit.** `max2` heeft een eigen runnerrecord, UUID en token. De
   config en legacy `.runner` van `scrum4me-server` worden nooit hierheen gekopieerd.
4. **Niet zelf deployen via Actions.** Runnerjobs draaien in DinD zonder
   host-Docker-socket; uitrol gaat handmatig/SSH vanaf `mac`.
