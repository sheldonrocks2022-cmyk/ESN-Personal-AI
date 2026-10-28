# ESN panel audit — preliminary source review (2026-10-28)

Target: https://panel.esnoffical.com

**Limitation:** The live panel could not be retrieved by the external browser inspection tools. No authenticated pages were accessed, and a complete visual scan cannot be claimed.

Existing repo reviewed: sheldonrocks2022-cmyk/Esn-2

- install-esn-theme-v1.sh injects /esn-theme/theme.css into a Pterodactyl Blade template and uses broad #app and button background CSS overrides. It backs up a Blade template and CSS if present.
- install-esn-login-v2.sh appends login-page styling using body:has(input[type="password"]) and backs up the stylesheet.
- These scripts are not proof of what is actually installed on the production VPS.

## Improvement opportunities
- Replace overly broad !important styling with tested component-aware visual styles.
- Introduce clean accessible mobile navigation, legible console, server resource charts, modern file/backup interfaces and consistent ESN branding.
- Confirm installed Pterodactyl version and template locations, real login/dashboard/console/file screenshots, responsive behavior and browser console errors.
- Avoid insecure direct editing. Stage and preview UI updates; retain and test rollback; do not change authentication, servers, integrations or customer information.

**No production panel changes were made.** Owner review and approval are required before any live deployment.
