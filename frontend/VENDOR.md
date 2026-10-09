# Art Design Pro Vendor Snapshot

This directory vendors Art Design Pro source for the Sentinel web-panel feasibility
study.

- Upstream repository: https://github.com/Daymychen/art-design-pro
- Snapshot commit: `f3aaf58eec1a0e988f162352c33862327a484f95`
- Snapshot date: 2026-06-30
- License: MIT, see `LICENSE`

Notes:

- The upstream `.git` directory was removed, so this is regular repository content,
  not a git submodule.
- The root repository ignores `.env`; therefore upstream `vendor/art-design-pro/.env`
  is present locally for investigation but is not tracked by Git. Future development
  should convert runtime env files to checked-in examples such as `.env.example`.
- This study phase should not edit Sentinel runtime code or run `pnpm clean:dev`.
  The cleanup script is destructive by design and should only be run on a committed
  branch after the team approves the migration approach.
