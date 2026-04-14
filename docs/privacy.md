# Privacy

This page is what the nanoMuse Android app does with your data. It is short because the app does little with it.

## Everything stays on the phone

The agent runs inside the app, in a Linux root file system on your phone. Conversations, memory, files the agent writes, scheduled tasks, skills and settings are stored in the app's private storage and, where you mount them, in folders you chose. There is no nanoMuse server, no account, no sign-in, no analytics, no crash reporting to us and no telemetry of any kind.

## What leaves the phone

- **Your model provider.** Messages, attached images and tool results are sent to the model endpoint you configured (阿里云百炼, DeepSeek, OpenAI, OpenRouter, your own vLLM or Ollama, …), under that provider's terms, with the API key you entered. The key is stored on the phone only.
- **The web, when the agent uses it.** Web search, page fetches, the in-app browser, MCP servers and command-line tools reach the sites and services they are for. What the agent sends is what you asked it to do.
- **Update check.** *Settings → About → Check for updates* asks the GitHub API for the latest release of `nano-muse/nanoMuse`. Nothing is sent besides the request itself.
- **Backups.** If you back up to a remote destination (SMB, WebDAV, SFTP, S3, FTP), the backup goes there, encrypted with the password you chose.

## Permissions

Each permission is asked for when a feature needs it and is used for that feature only: notifications for the agent's status and reminders; accessibility for operating other apps' screens, which is off until you turn it on; storage folders you mount; the microphone for voice input; contacts, calendar and location for the tools of the same names, each callable only after you granted them. Nothing is read in the background.

## Feedback

Bug reports go to GitHub Issues from *Settings → Feedback*; the report is pre-filled with the app version and the device model and nothing else. Do not paste API keys or private conversations into an issue.

## Changes

This page changes when the app's behaviour changes; the history is in the repository.
