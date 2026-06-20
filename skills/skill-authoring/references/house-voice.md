# House voice — the Assertion contract

Discipline/gate-bearing skills carry this block near the top of the body. It uses
engineering-assertion vocabulary, coherent with `contracts/skills/`. It is ours — it
does not reuse borrowed law/flag/rationalization-style section labels.

## Invariant
The single thing that must stay true. One sentence, a definition (not a command).

## Tripwires
2–4 observable signals you are about to violate the invariant. Phrase each as the
model's own internal excuse ("this is equivalent, no need to re-run").

## Proof
What you must run or show to demonstrate the invariant held. Proof = command output,
a diff, a transcript, a saved artifact, validator output, OR an explicit skip reason.

## Excuse → check
Two-column table: the excuse on the left, the concrete check that defeats it on the right.
