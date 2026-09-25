# Contributing

Thanks for helping! Bug reports from panels other than the tested Absoluta 16 are especially
valuable: please use the issue templates and attach the diagnostics file.

## Code structure

```
custom_components/bentel_absoluta/
├── itv2/            # protocol library, no Home Assistant dependencies
│   ├── framing.py   # 0x7E/0x7F, 7D 00/01/02 escaping, length, CRC-16/CCITT-FALSE
│   ├── messages.py  # encoding/decoding of the commands used by Absoluta
│   ├── events.py    # event log decoding (Appendix B texts)
│   └── client.py    # asyncio session: sequences/ACKs, handshake, login, polling, commands
├── alarm_control_panel.py, binary_sensor.py, sensor.py, switch.py, button.py
├── config_flow.py   # setup, reauth, reconfigure, options
└── brand/           # integration icon
tests/
├── fake_panel.py    # Absoluta panel simulator (ITv2 TCP server)
├── test_itv2.py     # protocol tests
└── test_integration.py  # tests inside a real Home Assistant
scripts/diagnose.py  # standalone connection test against a real panel
```

Protocol facts verified on real hardware are listed in [CLAUDE.md](CLAUDE.md): please read
them before changing the protocol code.

## Tests

Python 3.13:

```bash
pip install pytest-homeassistant-custom-component ruff
ruff check custom_components tests
pytest
```

Every new ITv2 command must also be implemented in `tests/fake_panel.py` and covered by a
test. The *Validate* workflow runs the tests, hassfest and the HACS validation on every push.

## Releases

1. Bump `version` in `custom_components/bentel_absoluta/manifest.json`.
2. Push and wait for the *Validate* workflow to pass.
3. Create a GitHub release with tag `vX.Y.Z` on `main`.

## Claude Code

In issues and pull requests you can write `@claude` to get help from
[Claude Code](https://github.com/anthropics/claude-code-action)
(workflow `.github/workflows/claude.yml`, runs only for users with write access).

<details>
<summary>Setting up the workflow in a fork</summary>

1. Create a GitHub App (*Settings → Developer settings → GitHub Apps*) with repository
   permissions **Contents**, **Issues**, **Pull requests** set to *Read & write*.
2. Generate a *private key* (`.pem`) and install the App on the repository.
3. Create an API key at <https://console.anthropic.com> (prepaid credit required).
4. In *Settings → Secrets and variables → Actions* add `APP_ID`, `APP_PRIVATE_KEY`
   (contents of the `.pem`) and `ANTHROPIC_API_KEY`.
   Instead of an API key you can use a Claude Pro/Max subscription token
   (`claude setup-token` → secret `CLAUDE_CODE_OAUTH_TOKEN` and, in the workflow,
   `claude_code_oauth_token:` instead of `anthropic_api_key:`).

Full guide: <https://github.com/anthropics/claude-code-action/blob/main/docs/setup.md>
</details>
