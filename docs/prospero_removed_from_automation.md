# PROSPERO Removed From Automation

Status: scope decision.

PROSPERO is not part of the automated Research Agent Bot path. The automated
registration and provenance path is OSF plus Derivation Web.

## Decision

- No PROSPERO web-form automation.
- No headless-browser submission.
- No claim that Research Agent Bot can programmatically obtain PROSPERO IDs.
- No blocking dependency on PROSPERO for AAA/L4/L5/L6 verdicts.

## Rationale

PROSPERO registration is human-led and web-form based. It can remain a manual
credibility step for selected papers, but it conflicts with the agent-to-agent
automation goal.

## Automated Path

The target automated path is:

1. Research Agent Bot generates a certified artifact bundle.
2. Derivation Web records provenance.
3. A sibling OSF publisher registers approved artifacts with OSF when live
   publishing is enabled.
4. The OSF record is written back to provenance after OSF verification.
5. A public reader renders the verified bundle when reader publication is
   enabled.

## Manual Optional Path

A human operator may still manually register selected flagship reviews in
PROSPERO and later record the returned ID as provenance metadata. That metadata
is external to the bot's automated certification.

## Wording Rule

Docs and public pages should say "OSF + provenance automated registration" for
the automated path. They should not imply automated PROSPERO submission.
