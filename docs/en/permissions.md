# macOS Permissions

kindle-pdf-capture requires two macOS permissions. Both must be granted to the terminal application you use (Terminal.app, iTerm2, etc.).

## Screen Recording

Required to capture window contents.

1. Open **System Settings** > **Privacy & Security** > **Screen Recording**
2. Click the **+** button and add your terminal application
3. Enable the checkbox next to it
4. Restart the terminal

## Accessibility

Required to send key events (page-turn arrow key) to Kindle.

1. Open **System Settings** > **Privacy & Security** > **Accessibility**
2. Click the **+** button and add your terminal application
3. Enable the checkbox next to it
4. Restart the terminal

## Verification

Run the following to check that both permissions are active:

```bash
kpc --out /tmp/test --max-pages 1 --start-delay 0
```

If either permission is missing, you will see a clear error message with instructions.

## Notes

- Permissions are per-application. Grant the permission to the terminal application that launches `kpc` (Terminal.app, iTerm2, Cursor, VSCode, etc.) — not to the Python binary inside the virtual environment.
- After granting permissions, restart the terminal for changes to take effect.
- On Apple Silicon Macs, permissions are enforced even for processes run with `sudo`.
- If you run `kpc` from Cursor or VSCode, grant the permission to `Cursor.app` or `VSCode.app` respectively.
