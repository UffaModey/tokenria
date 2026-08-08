# Security Policy

Tokenria is a local, single-user tool. By default (stages 1-6) it never makes a network call and
never sends your data anywhere — everything reads local files and writes to a local SQLite
database. The one planned exception is the optional auto-annotation feature (stage 7, not yet
built), which will call the Anthropic API using a key you supply yourself in a local `.env` file,
and only on an explicit per-record action you take — never automatically.

## Reporting a Vulnerability

If you find a security issue (e.g. a way for ingested data to execute code, an injection point in
a SQL query, or a way the app could be tricked into sending data somewhere it shouldn't), please
report it privately rather than opening a public issue:

- Email **uffamodey@gmail.com** with a description of the issue and steps to reproduce.
- You should get an acknowledgment within a few days. This is a solo-maintained project, so please
  be patient with turnaround time.

Please don't open a public GitHub issue for security reports until a fix is available.

## Supported Versions

This project is in early development (pre-1.0), with no formal release/support cycle yet. Security
fixes land on `main`; there's no older version being maintained in parallel.
