# Step 50: Owner-controlled long-term Jarvis memory

Jarvis already saves recent conversation history. Step 50 adds a **separate, persistent, encrypted owner-approved memory store** in its existing SQLite database. This is not an autonomous agent or general-purpose task planner yet.

- `/jarvis_remember topic:<label> note:<fact>` saves or updates one fact, encrypted with the existing `ESN_VAULT_KEY`.
- `/jarvis_memories` lists notes as an **owner-only, ephemeral** Discord response. Avoid adding sensitive personal details to memory.
- `/jarvis_forget topic:<label>` removes a note from the live memory table. Existing filesystem backups can retain earlier copies.
- Website `/assistant` and Discord `/jarvis_ask` use the same context from the 10 newest explicitly saved notes when configured for local Ollama (not external OpenAI API mode), but never automatically save chat content as permanent notes.
- Store up to 30 notes, 320 characters each. This is designed for a small model and won't substantially increase memory usage, though prompt tokens and inference latency can increase.

**Security:** Owner-only Discord permissions are essential. Notes are encrypted at rest with the existing vault key but may appear to the language model as **untrusted reference material** during inference. They are never decrypted into public API responses. Memory notes are included in local Ollama requests only, not sent to OpenAI when that provider is selected. Owner-only Discord memory listings are visible to Discord as ephemeral messages, not end-to-end encrypted. The local Ollama model stays on loopback. Don't store passwords, PINs, passkeys, payment information, or tokens here; put account secrets in the Connections vault. Keyword filtering can catch common secrets but isn't a substitute for your judgment. Back up the encrypted database and its key separately. For precise data erasure, securely handle backups as well as live rows.

Deployment: GitHub merge alone doesn't affect the live service. On the VPS, pull `main`, run the Python tests, then restart only `esn-jarvis` and `esn-jarvis-discord`. No need to restart Ollama, Wings, or Nginx. Both services remain assigned to the shared 8 GiB slice.

Acceptance tests: encrypted storage, normalization and update, deletion, limit enforcement, wrong-key behavior, AI context access, and the rule that chat itself does not automatically save notes.
