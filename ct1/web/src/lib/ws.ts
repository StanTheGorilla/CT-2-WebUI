type EventHandler = (data: Record<string, any>) => void;

export class WS {
    private socket: WebSocket | null = null;
    private handler: EventHandler;
    private url: string;
    private shouldReconnect = true;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private reconnectDelay = 1000;
    private maxDelay = 8000;
    onOpen: (() => void) | null = null;

    constructor(url: string, handler: EventHandler) {
        this.url = url;
        this.handler = handler;
    }

    connect() {
        this.shouldReconnect = true;
        this.openSocket();
    }

    private openSocket() {
        if (this.socket?.readyState === WebSocket.OPEN ||
            this.socket?.readyState === WebSocket.CONNECTING) return;
        try {
            this.socket = new WebSocket(this.url);
        } catch {
            this.scheduleReconnect();
            return;
        }
        this.socket.onopen = () => {
            this.reconnectDelay = 1000;
            this.onOpen?.();
        };
        this.socket.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                this.handler(data);
            } catch { /* ignore parse errors */ }
        };
        this.socket.onclose = () => {
            this.socket = null;
            this.scheduleReconnect();
        };
        this.socket.onerror = () => {
            // onclose will fire after onerror, triggering reconnect
        };
    }

    private scheduleReconnect() {
        if (!this.shouldReconnect) return;
        if (this.reconnectTimer) return;
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.openSocket();
        }, this.reconnectDelay);
        this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.maxDelay);
    }

    send(msg: Record<string, any>) {
        if (this.socket?.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(msg));
        }
    }

    disconnect() {
        this.shouldReconnect = false;
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        this.socket?.close();
        this.socket = null;
    }

    get connected(): boolean {
        return this.socket?.readyState === WebSocket.OPEN;
    }
}
