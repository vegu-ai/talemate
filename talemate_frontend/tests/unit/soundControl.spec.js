import { describe, it, expect, vi } from "vitest";
import { createSoundControl } from "@/utils/soundControl";

function makeControl(initialSound = { volume: 0.5, muted: false }) {
    const config = { sound: initialSound };
    const saves = [];
    let seq = 0;
    const save = vi.fn((patch, options) => {
        // the queue skips the send while no config has arrived — a refused send
        // reports through onError before it returns null
        if (!config.sound) {
            options.onError("not connected");
            return null;
        }
        const id = `cfg-${++seq}`;
        saves.push({ id, patch, options });
        return id;
    });
    const control = createSoundControl({ save, getSound: () => config.sound });
    // the component reconciles once on creation
    control.configChanged();

    // the app config broadcast is queued ahead of the completion, so the stored
    // section already carries the saved values when one arrives
    function complete(entry) {
        config.sound = { ...config.sound, ...entry.patch };
        entry.options.onComplete();
    }

    function refuse(entry) {
        entry.options.onError("settings save failed");
    }

    return { control, config, saves, save, complete, refuse };
}

function foreignSave(config, sound) {
    config.sound = { ...config.sound, ...sound };
}

describe("volume", () => {
    it("holds the released value until the save completes", () => {
        const { control, saves, complete } = makeControl();

        control.dragStart();
        control.input(0.8);
        control.dragEnd(0.8);

        expect(saves).toHaveLength(1);
        expect(saves[0].patch).toEqual({ volume: 0.8 });
        expect(control.effectiveVolume()).toBe(0.8);
        expect(control.committedVolume()).toBe(0.8);

        complete(saves[0]);

        expect(control.state.pendingVolume).toBeNull();
        expect(control.effectiveVolume()).toBe(0.8);
    });

    it("sends nothing when the released value is unchanged", () => {
        const { control, save } = makeControl();

        control.dragStart();
        control.dragEnd(0.5);

        expect(save).not.toHaveBeenCalled();
    });

    it("sends nothing on a blur without an edit", () => {
        const { control, save } = makeControl();

        control.setFocused(true);
        control.setFocused(false);

        expect(save).not.toHaveBeenCalled();
    });

    it("keeps a keyboard edit made while the release is still in flight", () => {
        const { control, saves, complete } = makeControl();

        control.setFocused(true);
        control.dragStart();
        control.input(0.4);
        control.dragEnd(0.4);
        control.input(0.41);
        complete(saves[0]);

        // the completion resyncs from the config, but not over an edit the
        // user made in the meantime
        expect(control.state.volumeLocal).toBe(0.41);
        expect(control.effectiveVolume()).toBe(0.41);

        control.setFocused(false);

        expect(saves).toHaveLength(2);
        expect(saves[1].patch).toEqual({ volume: 0.41 });
    });

    it("does not write back a foreign change that landed while focused", () => {
        const { control, config, save } = makeControl();

        control.setFocused(true);
        foreignSave(config, { volume: 0.3 });
        control.configChanged();

        expect(control.state.volumeLocal).toBe(0.5);

        control.setFocused(false);

        expect(save).not.toHaveBeenCalled();
        expect(control.state.volumeLocal).toBe(0.3);
    });

    it("ignores the answer to a superseded save", () => {
        const { control, saves, complete } = makeControl({ volume: 1, muted: false });

        control.dragStart();
        control.input(0.5);
        control.dragEnd(0.5);
        control.dragStart();
        control.input(0.2);
        control.dragEnd(0.2);

        expect(saves).toHaveLength(2);
        expect(control.state.pendingVolume.id).toBe(saves[1].id);

        complete(saves[0]);

        expect(control.state.pendingVolume.id).toBe(saves[1].id);
        expect(control.effectiveVolume()).toBe(0.2);

        complete(saves[1]);

        expect(control.state.pendingVolume).toBeNull();
        expect(control.effectiveVolume()).toBe(0.2);
    });

    it("follows the config again after a release back on the committed value", () => {
        const { control, config, save } = makeControl();

        control.setFocused(true);
        control.dragStart();
        control.input(0.7);
        control.input(0.5);
        control.dragEnd(0.5);

        expect(save).not.toHaveBeenCalled();

        foreignSave(config, { volume: 0.3 });
        control.configChanged();
        control.setFocused(false);

        expect(save).not.toHaveBeenCalled();
        expect(control.state.volumeLocal).toBe(0.3);
    });

    it("falls back to the config value when the save is refused", () => {
        const { control, saves, refuse } = makeControl();

        control.dragStart();
        control.input(0.8);
        control.dragEnd(0.8);
        refuse(saves[0]);

        expect(control.state.pendingVolume).toBeNull();
        expect(control.effectiveVolume()).toBe(0.5);
    });

    it("falls back to the config value when the save cannot be sent", () => {
        const { control, save, saves } = makeControl(null);

        control.dragStart();
        control.input(0.8);
        control.dragEnd(0.8);

        expect(save).toHaveBeenCalledTimes(1);
        expect(saves).toHaveLength(0);
        expect(control.state.pendingVolume).toBeNull();
        expect(control.effectiveVolume()).toBe(1);
    });
});

describe("mute", () => {
    it("mutes before the save is confirmed", () => {
        const { control, saves, complete } = makeControl();

        control.toggleMute();

        expect(saves[0].patch).toEqual({ muted: true });
        expect(control.isMuted()).toBe(true);

        complete(saves[0]);

        expect(control.state.pendingMuted).toBeNull();
        expect(control.isMuted()).toBe(true);
    });

    it("drops the override when the save is refused", () => {
        const { control, saves, refuse } = makeControl();

        control.toggleMute();
        refuse(saves[0]);

        expect(control.state.pendingMuted).toBeNull();
        expect(control.isMuted()).toBe(false);
    });

    it("keeps a mute that could not be sent and retries it when the config arrives", () => {
        const { control, config, saves, complete } = makeControl(null);

        control.toggleMute();

        expect(saves).toHaveLength(0);
        expect(control.isMuted()).toBe(true);

        config.sound = { volume: 1, muted: false };
        control.configChanged();

        expect(saves).toHaveLength(1);
        expect(saves[0].patch).toEqual({ muted: true });
        expect(control.isMuted()).toBe(true);

        complete(saves[0]);

        expect(control.state.pendingMuted).toBeNull();
        expect(control.isMuted()).toBe(true);
    });

    it("drops the retry when the arriving config already carries the mute", () => {
        const { control, config, save } = makeControl(null);

        control.toggleMute();
        config.sound = { volume: 1, muted: true };
        control.configChanged();

        expect(save).toHaveBeenCalledTimes(1);
        expect(control.state.pendingMuted).toBeNull();
        expect(control.isMuted()).toBe(true);
    });

    it("ignores the answer to a superseded mute save", () => {
        const { control, saves, complete } = makeControl();

        control.toggleMute();
        control.toggleMute();

        expect(saves).toHaveLength(2);
        expect(saves[1].patch).toEqual({ muted: false });

        complete(saves[0]);

        expect(control.isMuted()).toBe(false);

        complete(saves[1]);

        expect(control.state.pendingMuted).toBeNull();
        expect(control.isMuted()).toBe(false);
    });
});
