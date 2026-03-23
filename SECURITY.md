# Security Policy

## Scope

Open Apollo is a kernel module that runs with full system privileges. Security issues in this project can have serious consequences including system crashes, data corruption, or privilege escalation.

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Instead, please email **rolotrealanis@gmail.com** with:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You will receive a response within 48 hours. We will work with you to understand and address the issue before any public disclosure.

## What qualifies

- Kernel panics or crashes triggered by user input
- Memory corruption in the driver (buffer overflows, use-after-free)
- Privilege escalation via `/dev/ua_apollo0` or ioctl interface
- Information leaks from kernel memory to userspace
- Denial of service against the audio subsystem

## What doesn't qualify

- Audio glitches or quality issues
- PipeWire configuration problems
- Hardware compatibility failures
- The Apollo firmware itself (we don't control UA's firmware)

## Supported Versions

| Version | Supported |
|---------|-----------|
| v1.0.x  | ✅        |
| < v1.0  | ❌        |
