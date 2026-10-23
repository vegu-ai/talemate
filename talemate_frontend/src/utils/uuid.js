/**
 * The single source of UUIDs for the frontend.
 *
 * crypto.randomUUID() exists only in secure contexts, and Talemate is commonly
 * served over plain HTTP from a LAN host, where that call throws. The uuid
 * package works everywhere, so every UUID goes through here.
 */
import { v4 } from 'uuid';

export function newUuid() {
    return v4();
}
