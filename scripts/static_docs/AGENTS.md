# Static documentation regeneration

Read `.github/skills/regenerate-static-docs/SKILL.md` before changing this
pipeline or regenerating its output.

- Generate in a new staging directory. Never reset, clean, or overwrite a
  dirty checkout, and never include `server/` or scratch files in commits.
- Resolve the public built-site ref to a full commit SHA before downloading.
  Keep source and generator commits distinct in provenance.
- Derive versions, labels, counts, languages, and ports from the actual input
  or explicit parameters; do not assume the next release number or a path on
  a developer's machine.
- Include navigation-unreachable HTML pages. `.html.html` source duplicates
  are intentionally excluded.
- Convert only resolvable local targets to relative links with their exact
  filename casing. Preserve missing upstream targets as public URLs and
  report them; do not invent pages or silently approve extraction differences.
- Wget 404s are tolerated only when classified in diagnostics and complete
  source coverage and offline-reference audits pass. Network failures and
  other HTTP failures must stop publication.
- A syntax capture is optional and separate from the mirror. Require its
  explicit version and build; hash the unchanged bytes. Do not relabel an old
  capture or update assembled language data during regeneration.
- Release assets are immutable. Verify checksums before upload and refuse
  to overwrite a tag with different or incomplete assets.
- Run the unit suite and a complete source-snapshot regeneration when
  modifying crawl, finalization, or archive behavior.
