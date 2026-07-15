# Branching and weekly releases

`main` is always the current learner-facing release. Direct pushes to `main`
are prohibited: every change must reach it through a pull request.

## Weekly branches

Weekly branches use the cumulative `week-NN` naming scheme. Each branch
contains that week's learner state plus everything released in earlier weeks.
Future week development starts from the preceding weekly branch, not from an
older release or an unrelated feature branch.

The active weekly branch is the development branch for its upcoming release.
After it is released, it becomes a frozen historical record. A released weekly
branch must not be changed except for an urgent security or setup-breaking
correction.

## Release procedure

1. Confirm the active `week-NN` branch contains the intended cumulative learner
   state and passes the complete test suite.
2. Open a pull request from `week-NN` into `main`, verify it is safe and
   mergeable, and merge it without bypassing `main` protection.
3. Verify `main` now identifies the released learner state, then lock the
   released `week-NN` branch against ordinary pushes.
4. Create the next `week-NN` branch from the newly frozen preceding week and
   use it for the next week's development.

## Urgent corrections

Do not reopen a released weekly branch for routine improvements. If a released
state has an urgent security issue or a setup-breaking defect, make the
smallest possible correction through a reviewed pull request, temporarily
unlocking the weekly branch only as needed. Relock it immediately afterward,
and carry the same correction forward to `main` and every affected later weekly
branch.
