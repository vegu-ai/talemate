# Restoring Scenes from Backups

Talemate maintains automatic backup revisions of your scenes. You can restore any scene to a previous state from the Quick Load screen.

## How to restore a scene

1. From the main screen, locate your scene in the **Quick load** section
2. Click the three-dot menu (⋮) on the scene card
3. Select **Restore from Backup**

![Restore menu option](/talemate/img/0.33.0/restore-from-backup.png)

## Restore options

![Restore menu option](/talemate/img/0.33.0/restore-from-backup-dlg.png)

The backup restore dialog provides several restoration options:

- **Restore Earliest** - Returns the scene to its initial state (revision 0)
- **Restore Latest** - Restores the most recent saved state
- **Filter by date/time** - Find and restore to a specific point in time

When you use the date/time filter, Talemate will show the closest available revision to your selected time.

## Important notes

!!! warning
    Restoring creates a **new, unsaved scene** from the selected revision. Your original scene file will **not** be modified. This allows you to safely explore previous states without losing your current progress.

After restoration:

- The restored scene opens as a new, unsaved scene
- You must manually save it to preserve the restored state
- The original scene file remains unchanged in its current state
