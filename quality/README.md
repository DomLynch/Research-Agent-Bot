# Required development checks

`make quality` runs the complexity and duplication ratchets, Ruff, the real
revision lifecycle/Hypothesis tests and LOC budgets in randomized order, with
branch coverage of the revision boundary. CI also runs the full randomized
application suite. Install `.[dev]` first; missing plugins must fail, not skip.

Initial reviewed debt: 222 complexity findings and 52 clone fingerprints from
the existing source. Normal checks never update either baseline. New/worsened
functions and new clone fingerprints fail. Review baseline changes separately;
do not regenerate them to bless new code.

For a reproduced slow replay use VizTracer; for a hung process use py-spy.
Mutation testing needs a bounded function/test target. These investigations
remain task-specific, not automatic production instrumentation. Report their
actual evidence when applicable; never claim a profiler ran if it did not.

The shared Codex/Claude Stop hook invokes `.quality-gate.json`, including for
tracked edits that were auto-committed. Semble/Codegraph use is required by the
injected instructions and reviewer, not certified by a transcript-text parser.
This is completion enforcement, not a security boundary against disabling hooks
or editing a quality contract. CI must be configured as a required branch check
to prevent merging around it.
