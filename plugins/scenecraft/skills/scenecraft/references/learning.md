# Learning phase

Run learning after package and before complete, or after an unsuccessful run. `complete` closes an unsuccessful run's retrospective without changing its failed status. `note --action-key ... --learning ... --action ...` preserves unmeasured observations as inactive candidates, including failures before any evaluation exists.

For each successful or failed repair, record the trigger, what changed, the reusable learning, recommended next action, before and after scores, affected views, confidence, and evidence artifact paths. Preserve unsuccessful and ambiguous lessons as candidates because they help diagnosis even when they should not guide a future run.

A lesson is validated automatically only when two stored, hash-verified evaluations show that its aggregate score improves, confidence is at least `0.7`, and no required metric regresses. Name the before and after iteration numbers in `scenecraft learn`; never transcribe scores from the screen or accept caller-supplied values. Apply validated lessons to the next applicable run by including them in the frozen `applied-lessons.json` and Astra analysis request. Current references and user requirements override a lesson that does not fit.

Use a stable `action_key` for the decision being improved, such as `camera.hero-focal-length` or `facade.window-rhythm`. A newer validated lesson with the same key and overlapping workflow scope supersedes the previous lesson.

Keep project-specific observations in project memory. Promote a lesson to workflow memory only when it is generalized, contains no private data, and applies to a different object. Configure every participating project with `scenecraft configure-memory <project> <shared-lessons.json>`; the setting persists locally. `SCENECRAFT_WORKFLOW_MEMORY` remains an explicit override. Full lesson text is preserved under each run's learning directory.

Learning may influence structured plans and allowlisted worker settings. It must never generate or store Python, shell commands, secrets, or an instruction to bypass validation and acceptance gates.
