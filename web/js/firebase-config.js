/**
 * Firebase Configuration — Initialize Firebase and export Firestore instance.
 * Config values are read from <meta> tags (injected at build time via build.sh).
 * Fallback values are used for local development.
 *
 * Requires: Firebase compat SDK loaded via CDN before this script.
 */

(function () {
    'use strict';

    const getMeta = (name) => {
        const el = document.querySelector(`meta[name="${name}"]`);
        return el?.content || '';
    };

    const firebaseConfig = {
        apiKey: getMeta('firebase-api-key') || 'AIzaSyAjqU-DdNzJEiWELLi88kEA-XOfhvBbIyI',
        authDomain: 'amdlxd-history-9553f.firebaseapp.com',
        projectId: getMeta('firebase-project-id') || 'amdlxd-history-9553f',
        storageBucket: 'amdlxd-history-9553f.firebasestorage.app',
        messagingSenderId: '873970347748',
        appId: getMeta('firebase-app-id') || '1:873970347748:web:a7efe8b2d7adf2be5a06f1',
        measurementId: 'G-LWQW1ZB1QW',
    };

    // Initialize Firebase (compat mode)
    if (typeof firebase === 'undefined') {
        console.warn('[Firebase] SDK not loaded — history features disabled');
        return;
    }

    firebase.initializeApp(firebaseConfig);
    window.db = firebase.firestore();

    // Anonymous auth — Firestore rules require an authenticated uid and scope
    // every download-history document to its owner. Sign in once at startup and
    // expose a promise that resolves once the current user is available.
    window.firebaseAuthReady = new Promise((resolve) => {
        firebase.auth().onAuthStateChanged((user) => {
            if (user) {
                window.firebaseCurrentUser = user;
                resolve(user);
            } else {
                firebase.auth().signInAnonymously().catch((err) => {
                    console.error('[Firebase] Anonymous sign-in failed:', err);
                });
            }
        });
    });
})();
