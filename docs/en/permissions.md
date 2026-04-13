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

## Verification

Run the following to check that both permissions are active:

```bash
kpc --out /tmp/test --max-pages 1 --start-delay 0
```

If either permission is missing, you will see a clear error message with instructions.

## Notes

- Permissions are per-application. If you use a virtual environment or a different shell, the parent terminal application still needs the permission.
- After granting permissions, you may need to restart the terminal for changes to take effect.
- On Apple Silicon Macs, permissions are enforced even for processes run with `sudo`.
