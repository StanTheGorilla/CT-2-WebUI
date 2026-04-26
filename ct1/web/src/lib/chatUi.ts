type TurnLike = {
    detectedLang?: string;
    route?: string;
};

export const CHAT_MODE_ITEMS = ['auto', 'chat', 'design', 'code'] as const;

export const CHAT_MODE_LABELS: Record<(typeof CHAT_MODE_ITEMS)[number], string> = {
    auto: 'Auto',
    chat: 'Chat',
    design: 'Design',
    code: 'Code',
};

const PHASE_LABELS: Record<string, string> = {
    idle: '',
    routing: 'Classifying',
    planning: 'Planning',
    generating: 'Generating',
    polishing: 'Polishing',
    refining: 'Refining',
    validating: 'Validating',
    fixing: 'Fixing',
    done: '',
    spec_generating: 'Speccing',
    spec_validated: 'Spec ready',
    component_generating: 'Building',
    component_validating: 'Checking',
    assembling: 'Assembling',
};

const ROUTE_LABELS: Record<string, string> = {
    ROUTE_DESIGN: 'Design',
    ROUTE_CODE: 'Code',
    ROUTE_DIRECT: 'Chat',
    ROUTE_COMPUTER: 'Computer',
};

export const CONTEXT_SUMMARY_NOTE =
    'Older turns were compacted into this summary, and this is the context CT-2 is carrying into the next messages.';

export function getPhaseLabel(phase: string): string {
    return PHASE_LABELS[phase] ?? phase;
}

export function getRouteLabel(route: string): string {
    if (!route) return '';
    return ROUTE_LABELS[route] ?? humanizeRoute(route);
}

export function stripCodeFences(content: string): string {
    return content.replace(/^```\w*\s*\n/, '').replace(/\n?```\s*$/, '');
}

export function compactPreviewText(content: string, maxLines = 5): string {
    const trimmed = content.trim();
    if (!trimmed) return 'No summary content returned.';
    const lines = trimmed.split(/\r?\n/);
    const preview = lines.slice(0, maxLines).join('\n');
    return lines.length > maxLines ? `${preview}\n…` : preview;
}

export async function copyText(text: string): Promise<boolean> {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
        return false;
    }
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch {
        return false;
    }
}

export function getTurnOutputExt(turn: TurnLike): string {
    if (turn.detectedLang && turn.detectedLang !== 'text') return turn.detectedLang;
    if (turn.route === 'ROUTE_DESIGN') return 'html';
    if (turn.route === 'ROUTE_CODE') return 'py';
    return 'txt';
}

export function getTurnOutputFilename(turn: TurnLike): string {
    const ext = getTurnOutputExt(turn);
    return ext === 'html' ? 'output.html' : `output.${ext}`;
}

function humanizeRoute(route: string): string {
    const normalized = route.replace(/^ROUTE_/, '');
    if (!normalized) return '';
    return normalized.charAt(0) + normalized.slice(1).toLowerCase();
}
