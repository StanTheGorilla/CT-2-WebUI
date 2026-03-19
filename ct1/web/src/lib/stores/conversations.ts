import { writable } from 'svelte/store';

export interface ConversationSummary {
    id: string;
    title: string;
    preset: string;
    created_at: string;
    updated_at: string;
    message_count: number;
}

export const conversations = writable<ConversationSummary[]>([]);
export const activeConversationId = writable<string | null>(null);
export const sidebarOpen = writable<boolean>(false);

export async function loadConversations() {
    const res = await fetch('/api/conversations?limit=50');
    if (res.ok) {
        const data = await res.json();
        conversations.set(data);
    }
}

export async function createConversation(title: string = 'New conversation'): Promise<string | null> {
    const res = await fetch('/api/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
    });
    if (res.ok) {
        const data = await res.json();
        activeConversationId.set(data.id);
        await loadConversations();
        return data.id;
    }
    return null;
}

export async function deleteConversation(id: string) {
    await fetch(`/api/conversations/${id}`, { method: 'DELETE' });
    conversations.update(list => list.filter(c => c.id !== id));
    activeConversationId.update(curr => curr === id ? null : curr);
}

export async function renameConversation(id: string, title: string) {
    await fetch(`/api/conversations/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
    });
    conversations.update(list =>
        list.map(c => c.id === id ? { ...c, title } : c)
    );
}

export async function loadConversation(id: string) {
    const res = await fetch(`/api/conversations/${id}`);
    if (!res.ok) return null;
    return await res.json();
}
