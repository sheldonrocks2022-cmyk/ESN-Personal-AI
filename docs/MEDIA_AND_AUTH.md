# ESN Jarvis: Cinematic Media Studio and Authorized Authentication

Status: **planned design**, NOT an implemented video renderer, CAPTCHA solver, or passkey authenticator.

## Reference footage reviewed (2026-10-28)

The owner-supplied 20.19-second MP4 is H.264, 3840×2160, approximately 23.976 fps, with AAC audio. It is an anime edit with Sukuna/Gojo imagery, energetic typography, hard color contrasts, shake/zoom, motion blur, impact cuts, and an end card. The supplied YouTube Shorts URL could not be played during the preliminary assessment, so no exact comparison with that video is claimed.

## Cinematic editor architecture (build in an isolated media environment)

1. **Ingest:** Accept user-authorized source videos, image assets, voiceover, music and reference URLs. Store uploads outside the public repository. Verify codecs, duration, aspect ratio, copyright/licensing permissions, and file limits.
2. **Analysis:** Extract scene cuts, shot composition, subject tracks and beats; analyze reference edits for pace, motion, color, typography and transition design, rather than duplicating protected footage.
3. **Creative director:** Model produces an editable shot list, beat map, effect graph and revision plan. Choose 9:16/16:9 export, desired length, soundtrack, style and accessibility options.
4. **Compositor:** FFmpeg for cutting, decoding/encoding, speed ramps, audio mix and color operations; optional OpenCV/PySceneDetect/librosa for analysis; Remotion/Blender for titles, motion graphics and 3D elements. Permit external image/video generation providers through approved adapters. Verify provider terms.
5. **Render queue:** Real durable jobs with ID, worker, resource limits, cancellation, previews, retries, failure logs, actual files and checksums. Run intensive effects/transcoding on an isolated GPU-capable worker or external renderer; do not saturate production Wings/game servers.
6. **QA and revisions:** Check A/V synchronization, pacing, frame dropouts, output dimensions/fps, audio clipping, black frames, subtitle legibility, photosensitivity concerns (flash limits), and subjective visual ratings. Provide preview and a user-controlled revision loop.
7. **Delivery:** Export 4K or HD MP4 (depending on source/render hardware), 9:16 Shorts/Reels/TikTok and 16:9 YouTube. Provide thumbnail and caption suggestions, plus an editable project manifest. Publishing requires explicit owner confirmation.

### Success criteria

- Render an actual video from a set of authorized assets, with preview and downloadable artifact.
- Produce an editable timeline/project manifest; demonstrate beat sync and multiple effect layers.
- Verify render with ffprobe and automated media checks.
- Test a representative short against the owner-provided reference with before/after clips and reproducible job logs.
- Never claim subjective quality like '10x better' as a guarantee. Report constraints and actual outputs.

## Identity verification: human-in-the-loop only

Jarvis **must not** bypass CAPTCHA, bot challenges, identity checks, security prompts, or service rules. It should:

- Detect a human-verification or MFA checkpoint and **pause automation**.
- Notify the owner, open a secure remote browser handoff/session, and allow the owner to complete the legitimate check.
- Resume the already-authorized task only after success. Never send challenge codes or sensitive authentication data to an LLM or Discord chat log.
- Use official APIs and OAuth flows wherever possible instead of fragile username/password automation.
- Apply timeouts, revocable authorization, site-specific access controls, and audit logging.

## Passkeys: authorized WebAuthn flows

Jarvis may assist the owner to register and use **legitimate, site-supported passkeys** if the provider permits the flow.

- Implement standards-based WebAuthn registration and authentication; prefer a hardware-backed/non-exportable authenticator or supported secure passkey provider. The owner must approve registering each authenticator to each service/account.
- Require an already authorized account/session for enrollment and follow the site's verification prompts. Jarvis cannot independently create an account passkey in place of proof of account ownership.
- Store a credential handle/metadata and provider-approved secure authenticator linkage, not raw private keys in the LLM, prompts, public GitHub or ordinary text secrets.
- Do not create a 'universal passkey' or reuse a credential for unrelated relying parties. Honor relying-party ID/domain binding and user presence/verification requirements.
- Support listing, revoking, and replacing account-linked authenticators with owner approval; lock access behind stronger authentication than an exposed six-digit PIN alone.
- If a site disallows unattended authenticator use, require the owner to complete presence/verification. Do not emulate or spoof verification.

## Security guardrails

- Vault and saved cookies are secrets; never present them to generative models or worker logs.
- Protect against prompt injection from untrusted pages, video metadata, and user-submitted captions.
- No auto-purchasing media subscriptions, auto-posting to social accounts, or changing account recovery settings without owner approval.
- Record per-asset permissions, provenance, costs and render resource use.
- The PIN previously posted in chat must not be hardcoded or reused as the sole Internet-facing protection.
