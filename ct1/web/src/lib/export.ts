import type { Turn } from '$lib/stores/chat';

export function exportMarkdown(title: string, turns: Turn[]): string {
    let md = `# ${title}\n\n`;
    for (const t of turns) {
        if (t.role === 'user') {
            md += `## User\n\n${t.content}\n\n`;
        } else {
            md += `## Assistant`;
            if (t.route) md += ` (${t.route.replace('ROUTE_', '')})`;
            md += `\n\n${t.content}\n\n`;
        }
    }
    return md;
}

export function exportJSON(title: string, turns: Turn[]): string {
    return JSON.stringify({ title, messages: turns }, null, 2);
}

export function downloadText(content: string, filename: string, mime: string = 'text/plain') {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}
