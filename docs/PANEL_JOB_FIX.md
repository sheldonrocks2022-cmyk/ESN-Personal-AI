# Jarvis local-model tool-call reliability fix

The live Discord `/jarvis_ask` may receive malformed or over-specified tool arguments from small local models. The bridge now:

- Accepts a *matching redundant* `target=panel` for `panel_health` and `target=website` for `esn_website_health`, while rejecting mismatches, unknown options and unknown task types.
- Routes an explicit **single panel health-check job request** directly into the existing allowlisted SQLite queue without needing the model to generate perfect JSON.
- Returns the real queued job ID, not a claim that work has finished.
- Does not expand any production permissions, internet targets, login capabilities, or supported task types.

The owner can verify new jobs at `https://jarvis.esnoffical.com/tasks` after pulling and restarting Jarvis services on the host. Back up application code and run `python -m unittest discover -s tests -v` before restarting.

The fix was tested in GitHub Actions but **not deployed automatically** to the server.
