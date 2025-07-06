# Contributing to Talemate

## About This Project

Talemate is a **personal hobbyist project** that I maintain in my spare time. While I appreciate the community's interest and contributions, please understand that:

- This is primarily a passion project that I enjoy working on myself
- I have limited time for code reviews and prefer to spend that time developing fixes or new features myself
- Large contributions require significant review and testing time that takes away from my own development

For these reasons, I've established contribution guidelines that balance community involvement with my desire to actively develop the project myself.

## Contribution Policy

**I welcome small bugfix and small feature pull requests!** If you've found a bug and have a fix, or have a small feature improvement, I'd love to review it.

However, please note that **I am not accepting large refactors or major feature additions** at this time. This includes:
- Major architectural changes
- Large new features or significant functionality additions
- Large-scale code reorganization
- Breaking API changes
- Features that would require significant maintenance

## What is accepted

✅ **Small bugfixes** - Fixes for specific, isolated bugs

✅ **Small features** - Minor improvements that don't break existing functionality

✅ **Documentation fixes** - Typo corrections, clarifications in existing docs

✅ **Minor dependency updates** - Security patches or minor version bumps

## What is not accepted

❌ **Major features** - Large new functionality or systems

❌ **Large refactors** - Code reorganization or architectural changes

❌ **Breaking changes** - Any changes that break existing functionality

❌ **Major dependency changes** - Framework upgrades or replacements

## Submitting a PR

If you'd like to submit a bugfix or small feature:

1. **Open an issue first** - Describe the bug you've found or feature you'd like to add
2. **Keep it small** - Focus on one specific issue or small improvement
3. **Follow existing code style** - Match the project's current patterns
4. **Don't break existing functionality** - Ensure all existing tests pass
5. **Include tests** - Add or update tests that verify your fix or feature
6. **Update documentation** - If your changes affect behavior, update relevant docs

## Code Style

- Run `uv run pre-commit run --all-files` before submitting

## Testing

Ensure all tests pass by running:
```bash
uv run pytest tests/ -p no:warnings
```

## Questions?

If you're unsure whether your contribution would be welcome, please open an issue to discuss it first. This saves everyone time and ensures alignment with the project's direction.