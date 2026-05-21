# yc-email-bot

> A CLI tool that scrapes Y Combinator company listings and automates personalized outreach emails to founders.

---

## About The Project

Finding and reaching out to YC founders manually is tedious. `yc-email-bot` automates the pipeline: scrape company and founder data from the YC directory, resolve contact emails via DNS validation, and fire off personalized outreach — all from a single command.

**Core capabilities:**

- Scrapes YC company listings using BeautifulSoup
- Resolves and validates founder email addresses via DNS lookup
- Sends personalized outreach emails from the command line
- Packaged as an installable CLI tool (`email-me`)
- Test suite included with mocking support for HTTP and SMTP

---

## Built With

[![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org/)
[![BeautifulSoup](https://img.shields.io/badge/BeautifulSoup4-59666C?style=for-the-badge&logo=python&logoColor=white)](https://www.crummy.com/software/BeautifulSoup/)
[![Requests](https://img.shields.io/badge/Requests-20232A?style=for-the-badge&logo=python&logoColor=white)](https://requests.readthedocs.io/)
[![lxml](https://img.shields.io/badge/lxml-49A84C?style=for-the-badge&logo=python&logoColor=white)](https://lxml.de/)
[![dnspython](https://img.shields.io/badge/dnspython-0052CC?style=for-the-badge&logo=python&logoColor=white)](https://www.dnspython.org/)
[![pytest](https://img.shields.io/badge/pytest-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white)](https://docs.pytest.org/)

---

## Getting Started

### Prerequisites

Python 3.10+.

### Installation

```sh
git clone https://github.com/teddycitrus/yc-email-bot.git
cd yc-email-bot
pip install .
```

This installs the `email-me` CLI command. For development (includes pytest, mocking libs):

```sh
pip install ".[dev]"
```

### Configuration

Before running, set your sending email credentials as environment variables:

```sh
export SENDER_EMAIL="you@example.com"
export SENDER_PASSWORD="your_app_password"
```

> Use an app-specific password if you're sending via Gmail.

---

## Usage

```sh
email-me
```

The tool will scrape the YC directory, resolve emails for listed founders, and send outreach. Filter by batch or other criteria depending on the flags available in your build.

To run the test suite:

```sh
pytest tests/
```

---

## Self-host (free, 24/7)

A small Flask web UI is bundled. It accepts YC URLs / company domains via a text field or a `.txt` upload, plus a per-target count, and streams verified emails back live.

The cheapest path that supports real SMTP verification is an **Oracle Cloud Always Free** Ampere A1 Ubuntu VM. Outbound port 25 is generally available there, while every free serverless host (Vercel / Netlify / Render / HF Spaces / etc.) blocks it. One command after SSHing in:

```sh
curl -fsSL https://raw.githubusercontent.com/teddycitrus/yc-email-bot/main/deploy.sh | sudo bash
```

The script installs system packages, builds the venv, opens iptables ingress on port 80, probes outbound port 25 (falls back to permutation-only mode if it's blocked), installs a `systemd` unit, and prints the live URL. Re-run the same command to update. Don't forget to **open TCP/80 in your VCN Security List** in the Oracle console — that's the one step the script can't do for you.

Run locally instead:

```sh
pip install -e ".[web]"
python -m email_me.web
```

Then open <http://127.0.0.1:8000>.

---

## Roadmap

- [x] DNS-based email validation — resolves MX records to verify addresses before sending
- [x] Installable CLI via `pyproject.toml` — no manual script execution, just `email-me`
- [ ] Batch and tag filtering — target specific YC cohorts (e.g. W24, S25) from the command line
- [ ] Rate limiting and retry logic — avoid getting flagged as spam with configurable send delays

---

## Contributing

Contributions are welcome. To contribute:

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'Add your feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

### Top Contributors

- [@dzkchen](https://github.com/dzkchen) - minimum viable product
- [@teddycitrus](https://github.com/teddycitrus) - hosting/deployment

---

## License

Distributed under the MIT License. See `LICENSE` for more information.

---

## Contact

[@teddycitrus](https://github.com/teddycitrus)

Project: [https://github.com/teddycitrus/yc-email-bot](https://github.com/teddycitrus/yc-email-bot)
