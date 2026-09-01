/**
 * Download History Service Layer — Firestore operations for download tracking.
 *
 * Provides:
 *   addDownloadHistory(item)                  — Write a download record
 *   subscribeToDownloadHistory(callback, max) — Real-time listener (returns unsubscribe fn)
 *   clearDownloadHistory()                    — Delete all history documents
 *   incrementDownloadCount()                  — Atomic counter bump
 *   subscribeToDownloadCount(callback)        — Real-time counter listener (returns unsubscribe fn)
 *
 * Requires: firebase-config.js loaded first (provides window.db, firebaseAuthReady,
 * firebaseCurrentUser).
 *
 * Firestore rules scope every download-history document to the authenticated
 * user's uid (`user_id` field), so all reads/writes filter by the current user.
 */

(function () {
    'use strict';

    const COLLECTION_NAME = 'download_history';
    const STATS_COLLECTION = 'stats';
    const STATS_DOC_ID = 'general';
    const MAX_HISTORY_ITEMS = 50;

    // Resolves once the current user is authenticated (or rejects on failure).
    function getCurrentUser() {
        return window.firebaseAuthReady.then(() => window.firebaseCurrentUser);
    }

    // ── Add a Download Record ──────────────────────────────────────────────

    /**
     * Write a new download record to Firestore.
     * @param {Object} item - { title, artist, type, codec, date }
     */
    window.addDownloadHistory = async function (item) {
        if (!window.db) return;
        try {
            const user = await getCurrentUser();
            await window.db.collection(COLLECTION_NAME).add({
                ...item,
                user_id: user.uid,
                timestamp: firebase.firestore.FieldValue.serverTimestamp(),
            });
        } catch (error) {
            console.error('Failed to add download history:', error);
            throw error;
        }
    };

    // ── Subscribe to History (Real-Time) ───────────────────────────────────

    /**
     * Subscribe to the current user's most recent download history items.
     * @param {Function} callback - Called with array of history items on each change
     * @param {number} maxItems - Max items to return (default: 50)
     * @returns {Function} Unsubscribe function
     */
    window.subscribeToDownloadHistory = function (callback, maxItems = MAX_HISTORY_ITEMS) {
        if (!window.db) return () => {};
        let unsubscribe = () => {};

        getCurrentUser()
            .then((user) => {
                unsubscribe = window.db
                    .collection(COLLECTION_NAME)
                    .where('user_id', '==', user.uid)
                    .orderBy('timestamp', 'desc')
                    .limit(maxItems)
                    .onSnapshot(
                        (snapshot) => {
                            const items = snapshot.docs.map((doc) => ({
                                id: doc.id,
                                ...doc.data(),
                            }));
                            callback(items);
                        },
                        (error) => {
                            console.error('Error listening to download history:', error);
                        }
                    );
            })
            .catch((error) => {
                console.error('History subscription requires auth:', error);
            });

        return () => unsubscribe();
    };

    // ── Clear History ──────────────────────────────────────────────────────

    /**
     * Delete all download_history documents owned by the current user.
     */
    window.clearDownloadHistory = async function () {
        if (!window.db) return;
        try {
            const user = await getCurrentUser();
            const snapshot = await window.db
                .collection(COLLECTION_NAME)
                .where('user_id', '==', user.uid)
                .get();
            const docs = snapshot.docs;
            const CHUNK_SIZE = 450;
            for (let i = 0; i < docs.length; i += CHUNK_SIZE) {
                const batch = window.db.batch();
                const chunk = docs.slice(i, i + CHUNK_SIZE);
                chunk.forEach((doc) => batch.delete(doc.ref));
                await batch.commit();
            }
        } catch (error) {
            console.error('Failed to clear download history:', error);
            throw error;
        }
    };

    // ── Increment Global Counter ───────────────────────────────────────────

    /**
     * Atomically increment the total_downloads counter.
     * Auto-creates the stats document on first call.
     *
     * Note: `stats` is server-write-only in the Firestore rules; client-side
     * increments are best-effort and will no-op when rejected. The canonical
     * counter lives behind a Cloud Function in production.
     */
    window.incrementDownloadCount = async function () {
        if (!window.db) return;
        const statsRef = window.db.collection(STATS_COLLECTION).doc(STATS_DOC_ID);
        try {
            await statsRef.update({
                total_downloads: firebase.firestore.FieldValue.increment(1),
            });
        } catch (error) {
            const code = error?.code;
            const msg = error?.message || '';
            if (code === 'not-found' || msg.includes('No document to update')) {
                // First-ever download — create the stats document
                await statsRef.set({ total_downloads: 1 });
            } else {
                // Permission-denied from read-only stats rules is expected;
                // never break the download flow over a counter.
                console.warn('Failed to increment download count:', error);
            }
        }
    };

    // ── Subscribe to Global Counter (Real-Time) ────────────────────────────

    /**
     * Subscribe to the global download count.
     * @param {Function} callback - Called with the current count number
     * @returns {Function} Unsubscribe function
     */
    window.subscribeToDownloadCount = function (callback) {
        if (!window.db) return () => {};
        const statsRef = window.db.collection(STATS_COLLECTION).doc(STATS_DOC_ID);
        return statsRef.onSnapshot(
            (doc) => {
                if (doc.exists) {
                    callback(doc.data().total_downloads || 0);
                } else {
                    callback(0);
                }
            },
            (error) => {
                console.error('Error listening to download count:', error);
            }
        );
    };
})();