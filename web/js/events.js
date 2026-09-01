/**
 * SSE-based event stream client.
 * Replaces the WebSocket client for serverless compatibility.
 *
 * Uses fetch() with ReadableStream to parse SSE manually,
 * since native EventSource doesn't support custom headers
 * (we need Authorization: Bearer <token>).
 */
class EventStream {
    constructor() {
        this.handlers = {};
        this._mainAbortController = null;
        this._jobAbortControllers = new Map();
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 2000; // ms
        this._isDisconnected = false;
    }

    /**
     * Connect to the SSE endpoint for all events.
     * Uses a custom fetch-based approach to include Authorization header.
     */
    async connect() {
        this._isDisconnected = false;
        const token = AuthStorage.getToken();
        if (!token) {
            console.error('EventStream: No auth token available');
            return;
        }

        // Abort any existing main connection
        if (this._mainAbortController) {
            this._mainAbortController.abort();
        }
        this._mainAbortController = new AbortController();

        const url = `${api.baseUrl}/api/events`;

        try {
            const response = await fetch(url, {
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Accept': 'text/event-stream',
                },
                signal: this._mainAbortController.signal,
            });

            if (!response.ok) {
                throw new Error(`SSE connection failed: ${response.status}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            this.reconnectAttempts = 0;
            this._emit('connected');

            while (true) {
                const { done, value } = await reader.read();
                if (done) {
                    if (!this._isDisconnected) {
                        this._tryReconnect();
                    }
                    break;
                }

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // Keep incomplete line in buffer

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const msg = JSON.parse(line.slice(6));
                            this._emit(msg.type, msg.data);
                        } catch (e) {
                            console.warn('EventStream: Failed to parse message', e);
                        }
                    }
                }
            }
        } catch (err) {
            if (err.name === 'AbortError') {
                console.log('EventStream: Connection aborted');
                return;
            }
            console.error('EventStream error:', err);
            this._emit('disconnected');
            if (!this._isDisconnected) {
                this._tryReconnect();
            }
        }
    }

    /**
     * Connect to SSE for a specific job.
     */
    async connectJob(jobId) {
        const token = AuthStorage.getToken();
        if (!token) return;

        if (this._jobAbortControllers.has(jobId)) {
            this._jobAbortControllers.get(jobId).abort();
        }
        const jobAbort = new AbortController();
        this._jobAbortControllers.set(jobId, jobAbort);

        const url = `${api.baseUrl}/api/events/${jobId}`;

        try {
            const response = await fetch(url, {
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Accept': 'text/event-stream',
                },
                signal: jobAbort.signal,
            });

            if (!response.ok) throw new Error(`SSE failed: ${response.status}`);

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const msg = JSON.parse(line.slice(6));
                            this._emit(msg.type, msg.data);
                        } catch (e) {
                            console.warn('EventStream: parse error', e);
                        }
                    }
                }
            }
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('EventStream job error:', err);
        } finally {
            this._jobAbortControllers.delete(jobId);
        }
    }

    /** Register an event handler. */
    on(event, handler) {
        if (!this.handlers[event]) {
            this.handlers[event] = [];
        }
        this.handlers[event].push(handler);
    }

    /** Remove an event handler. */
    off(event, handler) {
        if (this.handlers[event]) {
            this.handlers[event] = this.handlers[event].filter(cb => cb !== handler);
        }
    }

    /** Disconnect and clean up. */
    disconnect() {
        this._isDisconnected = true;
        if (this._mainAbortController) {
            this._mainAbortController.abort();
            this._mainAbortController = null;
        }
        for (const controller of this._jobAbortControllers.values()) {
            controller.abort();
        }
        this._jobAbortControllers.clear();
    }

    /** Auto-reconnect with exponential backoff. */
    _tryReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('EventStream: Max reconnect attempts reached');
            this._emit('connection_lost');
            return;
        }
        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
        console.log(`EventStream: Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
        setTimeout(() => this.connect(), delay);
    }

    /** Emit an event to all listeners. */
    _emit(type, data) {
        const callbacks = this.handlers[type] || [];
        for (const cb of callbacks) {
            try {
                cb(data);
            } catch (e) {
                console.error(`[EventStream] Listener error for "${type}":`, e);
            }
        }
    }
}

// Global singleton
const eventStream = new EventStream();
