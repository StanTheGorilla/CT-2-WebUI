import { writable, get } from 'svelte/store';
import { WS } from '$lib/ws';
import { preferences } from '$lib/stores/preferences';
import { activeConversationId, loadConversations, updateConversationTitle } from '$lib/stores/conversations';

export interface Attachment {
    type: 'image' | 'file';
    name: string;
    /** data:image/...;base64,... — only for images */
    dataUrl: string;
    /** text content — only for text files */
    textContent?: string;
}

export interface SearchResult {
    title: string;
    url: string;
    snippet: string;
}

export interface SearchActivity {
    query: string;
    results: SearchResult[];
    done: boolean;
    error?: string | null;
}

export interface Turn {
    role: 'user' | 'assistant';
    content: string;
    /** Frontend-only: attached images */
    attachments?: Attachment[];
    /** Frontend-only: was this a code response? */
    isCode?: boolean;
    /** Frontend-only: route label */
    route?: string;
    /** Frontend-only: pipeline metadata preserved per turn */
    plan?: Plan | null;
    specialistData?: SpecialistData | null;
    reflection?: Reflection | null;
    review?: ReviewResult | null;
    thinking?: string;
    draftThinking?: string;
    messageId?: string;
    feedback?: number;
    activeSearches?: SearchActivity[];
    fetchedContent?: { url: string; title: string; content: string;
                       contentLength: number; truncated: boolean }[];
    webSearchResults?: SearchResult[];
    webSearchQuery?: string;
    /** Detected language identifier from backend (e.g. 'python', 'html') */
    detectedLang?: string;
    /** Explanation text written before the code fence (code mode only) */
    explanation?: string;
    /** Files written to workspace (computer mode) */
    files?: Array<{ path: string; lang: string }>;
    /** Previous response versions saved on retry (oldest first) */
    alternatives?: string[];
    /** Currently displayed version index; alternatives.length = current/latest */
    altIndex?: number;
    /** True for the synthetic summary turn inserted after compaction */
    isCompacted?: boolean;
    /** Original persisted message position when loaded from history */
    messagePosition?: number;
    /** Backend reported finish reason for the final generation call */
    finishReason?: string;
    /** True if the backend still hit a length stop after auto-continuation */
    truncated?: boolean;
    /** Number of automatic compact-and-continue passes used */
    autoContinuations?: number;
}

export interface Reflection {
    self_score: number;
    lesson: string;
    [key: string]: any;
}

export interface SpecialistData {
    _route?: string;
    // ROUTE_DESIGN
    project_type?: string;
    audience?: string;
    mood?: string[];
    theme?: string;
    sections?: string[];
    color_hints?: string[];
    special?: string[];
    // ROUTE_CODE
    language?: string;
    type?: string;
    requirements?: string[];
    edge_cases?: string[];
    output_format?: string;
    // ROUTE_COMPUTER
    framework?: string;
    files?: string[];
    run_command?: string;
    // ROUTE_DIRECT
    topic?: string;
    answer_type?: string;
    depth?: string;
    key_points?: string[];
    // Legacy
    palette?: Record<string, string>;
    typography?: Record<string, string>;
    rationale?: string;
}

export interface ReviewResult {
    pass: boolean;
    critical_issues: string[];
    fix_instructions: string;
}

export interface PlanComponent {
    id: number;
    name: string;
    description: string;
}

export interface Plan {
    output_type: string;
    components: PlanComponent[];
    complexity: string;
}

export type ModeOverride = 'auto' | 'design' | 'code' | 'chat' | 'computer';

export interface AtlasCandidate {
    index: number;
    score: number | null;
    testsPassed: number | null;
    testsTotal: number | null;
    status: 'pending' | 'generating' | 'scored' | 'selected' | 'failed';
}

export interface AtlasEffort {
    k: number;
    difficulty: number;
    tier: string;
}

interface ChatState {
    conversationId: string | null;
    conversation: Turn[];
    events: Record<string, any>[];
    cancelRequested: boolean;
    route: string;
    plan: Plan | null;
    specialistData: SpecialistData | null;

    review: ReviewResult | null;
    reflection: Reflection | null;
    response: string;
    thinking: string;
    draft: string;
    draftThinking: string;
    streamingText: string;
    streamingThinking: string;
    checklist: { item: string; done: boolean }[];
    validationIssues: string[];
    editing: boolean;
    warning: string;
    modeOverride: ModeOverride;
    undoStack: string[];
    terminalOutput: string;
    pendingCommands: string[];
    pendingApproval: { id: string; command: string } | null;
    contextFiles: string[];
    workspaceId: string | null;
    phase: 'idle' | 'routing' | 'planning' | 'generating'
         | 'polishing' | 'refining' | 'validating' | 'fixing' | 'done'
         | 'spec_generating' | 'spec_validated'
         | 'component_generating' | 'component_validating'
         | 'assembling';
    designSpec: Record<string, any> | null;
    componentProgress: {
        id: string;
        index: number;
        total: number;
        status: 'generating' | 'validated' | 'patching' | 'fallback';
    }[];
    tokenCount: number;
    genStartTime: number;
    tokensPerSec: number;
    isCompacting: boolean;
    savedFiles: string[];
    fetchingUrls: { url: string; status: 'fetching' | 'done' | 'failed'; error?: string }[];
    fetchedContent: { url: string; title: string; content: string;
                      contentLength: number; truncated: boolean }[];
    activeSearches: SearchActivity[];
    // Atlas state
    atlasActive: boolean;
    atlasCandidates: AtlasCandidate[];
    atlasPhase: 'estimating' | 'generating' | 'testing' | 'selecting' | 'repairing' | null;
    atlasEffort: AtlasEffort | null;
    forceClearKvOnNextThink: boolean;
}

const initial: ChatState = {
    conversationId: null,
    conversation: [],
    events: [],
    cancelRequested: false,
    route: '',
    plan: null,
    specialistData: null,

    review: null,
    reflection: null,
    response: '',
    thinking: '',
    draft: '',
    draftThinking: '',
    streamingText: '',
    streamingThinking: '',
    checklist: [],
    validationIssues: [],
    editing: false,
    warning: '',
    modeOverride: 'chat',
    undoStack: [],
    terminalOutput: '',
    pendingCommands: [],
    pendingApproval: null,
    contextFiles: [],
    workspaceId: null,
    phase: 'idle',
    designSpec: null,
    componentProgress: [],
    tokenCount: 0,
    genStartTime: 0,
    tokensPerSec: 0,
    isCompacting: false,
    savedFiles: [],
    fetchingUrls: [],
    fetchedContent: [],
    activeSearches: [],
    atlasActive: false,
    atlasCandidates: [],
    atlasPhase: null,
    atlasEffort: null,
    forceClearKvOnNextThink: false,
};

export const chat = writable<ChatState>({ ...initial });

export const pendingInputPrompt = writable<string>('');

// Model context size — set once from /api/config so sendThink can decide when to compact
let _contextSize = 0;
export function setContextSize(n: number) { _contextSize = n; }

function estimateContentTokens(content: unknown): number {
    if (typeof content === 'string') {
        return Math.round(content.length / 3.0);
    }
    if (Array.isArray(content)) {
        return content.reduce((acc, part) => {
            if (!part || typeof part !== 'object') return acc;
            const typedPart = part as Record<string, any>;
            if (typedPart.type === 'text') {
                return acc + Math.round(String(typedPart.text ?? '').length / 3.0);
            }
            if (typedPart.type === 'image_url') {
                // Images consume prompt budget too, but nowhere near the size of the data URL.
                return acc + 85;
            }
            return acc + 16;
        }, 0);
    }
    return Math.round(JSON.stringify(content ?? '').length / 3.0);
}

let ws: WS | null = null;

// Saved when regenerate() removes the last assistant turn, attached to the new turn on done.
let _pendingAlt: string | null = null;
let _pendingPrevAlts: string[] = [];

const ALLOWED_CANCEL_EVENTS = new Set([
    'conversation_id',
    'title_update',
    'file_saved',
    'terminal_output',
    'command_approval_request',
]);

function clearWorkspaceSessionState(s: ChatState) {
    s.contextFiles = [];
    s.pendingCommands = [];
    s.pendingApproval = null;
    s.savedFiles = [];
    s.terminalOutput = '';
}

function applyWorkspaceId(s: ChatState, id: string | null) {
    if (s.workspaceId !== id) {
        clearWorkspaceSessionState(s);
    }
    s.workspaceId = id;
    if (id) {
        s.modeOverride = 'computer';
    }
}

function clearTransientTurnState(s: ChatState) {
    s.streamingText = '';
    s.streamingThinking = '';
    s.checklist = [];
    s.validationIssues = [];
    s.review = null;
    s.reflection = null;
    s.warning = '';
    s.fetchingUrls = [];
    s.fetchedContent = [];
    s.activeSearches = [];
    s.pendingCommands = [];
    s.designSpec = null;
    s.componentProgress = [];
    s.editing = false;
    s.draft = '';
    s.draftThinking = '';
    s.tokenCount = 0;
    s.genStartTime = 0;
    s.tokensPerSec = 0;
    s.atlasActive = false;
    s.atlasCandidates = [];
    s.atlasPhase = null;
    s.atlasEffort = null;
}

function cloneSearchActivities(searches: SearchActivity[]): SearchActivity[] {
    return searches.map((search) => ({
        ...search,
        results: [...search.results],
    }));
}

function findLastPendingSearchIndex(searches: SearchActivity[]): number {
    for (let i = searches.length - 1; i >= 0; i--) {
        if (!searches[i].done) return i;
    }
    return searches.length - 1;
}

function handleEvent(data: Record<string, any>) {
    chat.update((s) => {
        s.events = [...s.events, data];

        if (s.cancelRequested && !ALLOWED_CANCEL_EVENTS.has(data.event)) {
            return s;
        }

        switch (data.event) {
            case 'conversation_id':
                s.conversationId = data.id;
                break;
            case 'title_update':
                updateConversationTitle(data.id, data.title);
                break;
            case 'routing':
                s.phase = 'routing';
                break;
            case 'routed':
                s.route = data.route;
                s.phase = 'planning';
                break;
            case 'planned':
                s.phase = 'planning';
                s.plan = data.plan || null;
                break;
            case 'generating':
                s.phase = 'generating';
                s.editing = !!data.editing;
                // Push previous code to undo stack before edit overwrites it
                if (s.editing && s.conversation.length > 0) {
                    const lastAssistant = [...s.conversation].reverse().find(t => t.role === 'assistant' && t.isCode);
                    if (lastAssistant) {
                        s.undoStack = [...s.undoStack.slice(-4), lastAssistant.content];
                    }
                }
                s.streamingText = '';
                s.streamingThinking = '';
                s.tokenCount = 0;
                s.genStartTime = 0;
                s.tokensPerSec = 0;
                break;
            case 'token':
                if (data.kind === 'thinking') {
                    s.streamingThinking += data.text;
                } else {
                    s.streamingText += data.text;
                }
                s.tokenCount++;
                if (!s.genStartTime) {
                    s.genStartTime = Date.now();
                }
                const elapsed = (Date.now() - s.genStartTime) / 1000;
                if (elapsed > 0.3) {
                    s.tokensPerSec = Math.round(s.tokenCount / elapsed);
                }
                break;
            case 'draft':
                s.draft = data.text;
                s.draftThinking = data.thinking || '';
                break;
            case 'checklist':
                s.checklist = data.items || [];
                break;
            case 'polishing':
                s.phase = 'polishing';
                s.streamingThinking = '';
                break;
            case 'refining':
                s.phase = 'refining';
                // Keep streamingText visible (shows draft in preview)
                // Refined output will replace it via 'polished' event
                s.streamingThinking = '';
                break;
            case 'polished':
                // CSS was improved — replace streamingText with polished version
                if (data.code) {
                    s.streamingText = data.code;
                }
                break;
            case 'validating':
                s.phase = 'validating';
                s.validationIssues = data.issues || [];
                s.review = data.review || null;
                break;
            case 'validated':
                s.validationIssues = [];
                s.review = data.review || null;
                break;
            case 'fixing':
                s.phase = 'fixing';
                s.streamingText = '';
                s.streamingThinking = '';
                break;
            case 'done': {
                // If stopGeneration already committed the partial turn, skip
                const lastTurn = s.conversation[s.conversation.length - 1];
                if (s.phase === 'done' && lastTurn?.role === 'assistant') {
                    break;
                }
                s.isCompacting = false;
                s.phase = 'done';
                s.response = data.response || s.streamingText || '';
                s.thinking = data.thinking || s.streamingThinking || '';
                s.streamingThinking = '';
                s.streamingText = '';
                if (s.genStartTime && s.tokenCount > 0) {
                    const elapsed = (Date.now() - s.genStartTime) / 1000;
                    s.tokensPerSec = elapsed > 0 ? Math.round(s.tokenCount / elapsed) : 0;
                }
                if (!s.draft) s.draft = data.draft || '';
                if (!s.draftThinking) s.draftThinking = data.draft_thinking || '';
                if (!s.route) s.route = data.route || '';
                if (!s.specialistData) s.specialistData = data.specialist_data || null;
                s.reflection = data.reflection;
                if (data.truncated) {
                    s.warning = 'The response still hit the context limit after auto-continuation, so it may be incomplete.';
                } else if (s.warning.startsWith('The response still hit the context limit')) {
                    s.warning = '';
                }
                // Only treat as code file if the route is code-type AND actual code was detected
                // (detected_lang 'text' means the AI answered in prose — show it as a chat bubble)
                const _detectedLang = data.detected_lang ?? 'text';
                const codeRoute = (s.route === 'ROUTE_DESIGN' || s.route === 'ROUTE_CODE' || s.route === 'ROUTE_COMPUTER')
                    && _detectedLang !== 'text';
                const newAlts = _pendingAlt !== null
                    ? [..._pendingPrevAlts, _pendingAlt]
                    : undefined;
                const newAltIdx = newAlts ? newAlts.length : undefined;
                _pendingAlt = null;
                _pendingPrevAlts = [];
                s.conversation = [
                    ...s.conversation,
                    {
                        role: 'assistant',
                        content: s.response,
                        isCode: codeRoute,
                        route: s.route,
                        plan: s.plan,
                        specialistData: s.specialistData,
                        reflection: s.reflection,
                        review: s.review,
                        thinking: s.thinking,
                        draftThinking: s.draftThinking,
                        activeSearches: s.activeSearches.length > 0
                            ? cloneSearchActivities(s.activeSearches)
                            : undefined,
                        fetchedContent: s.fetchedContent.length > 0 ? s.fetchedContent : undefined,
                        detectedLang: _detectedLang,
                        explanation: data.explanation || undefined,
                        files: data.files ?? [],
                        alternatives: newAlts,
                        altIndex: newAltIdx,
                        finishReason: data.finish_reason || undefined,
                        truncated: !!data.truncated,
                        autoContinuations: Number(data.auto_continuations || 0),
                    },
                ];
                break;
            }
            // ── Precision-Design pipeline events ──
            case 'spec_generating':
                s.phase = 'spec_generating';
                s.componentProgress = [];
                s.designSpec = null;
                s.streamingText = '';
                s.streamingThinking = '';
                s.tokenCount = 0;
                s.genStartTime = 0;
                s.tokensPerSec = 0;
                break;
            case 'spec_validated':
                s.phase = 'spec_validated';
                s.designSpec = data.spec || null;
                break;
            case 'spec_failed':
                s.warning = `Spec validation failed: ${(data.errors || []).join(', ')}`;
                break;
            case 'component_generating': {
                s.phase = 'component_generating';
                const cid = data.component_id;
                const idx = data.index ?? 0;
                const total = data.total ?? 0;
                const existing = s.componentProgress.findIndex(c => c.id === cid);
                if (existing >= 0) {
                    s.componentProgress[existing] = { id: cid, index: idx, total, status: 'generating' };
                } else {
                    s.componentProgress = [...s.componentProgress, { id: cid, index: idx, total, status: 'generating' }];
                }
                break;
            }
            case 'component_validated': {
                const cvid = data.component_id;
                const cidx = s.componentProgress.findIndex(c => c.id === cvid);
                if (cidx >= 0) {
                    s.componentProgress[cidx] = { ...s.componentProgress[cidx], status: 'validated' };
                }
                break;
            }
            case 'component_patching': {
                const cpid = data.component_id;
                const cpidx = s.componentProgress.findIndex(c => c.id === cpid);
                if (cpidx >= 0) {
                    s.componentProgress[cpidx] = { ...s.componentProgress[cpidx], status: 'patching' };
                }
                break;
            }
            case 'component_fallback': {
                const cfid = data.component_id;
                const cfidx = s.componentProgress.findIndex(c => c.id === cfid);
                if (cfidx >= 0) {
                    s.componentProgress[cfidx] = { ...s.componentProgress[cfidx], status: 'fallback' };
                }
                break;
            }
            case 'assembling':
                s.phase = 'assembling';
                s.streamingText = '';
                break;
            case 'retrying':
                s.phase = 'fixing';
                s.warning = data.message || 'Retrying broken sections...';
                s.streamingText = '';
                s.streamingThinking = '';
                break;
            case 'file_saved':
                // Computer mode: file written to workspace
                if (data.path && !s.savedFiles.includes(data.path)) {
                    s.savedFiles = [...s.savedFiles, data.path];
                }
                break;
            case 'terminal_output':
                // Computer mode: command execution output
                s.terminalOutput += data.text || '';
                break;
            case 'command_approval_request':
                s.pendingApproval = { id: data.approval_id, command: data.command };
                break;
            case 'run_commands':
                // Computer mode: AI wants to run these commands in the interactive terminal
                if (Array.isArray(data.commands) && data.commands.length > 0) {
                    s.pendingCommands = [...s.pendingCommands, ...data.commands];
                }
                break;
            case 'web_searching':
                s.activeSearches = [
                    ...s.activeSearches,
                    {
                        query: data.query || '',
                        results: [],
                        done: false,
                        error: null,
                    },
                ];
                break;
            case 'web_search_results': {
                const idx = findLastPendingSearchIndex(s.activeSearches);
                const nextSearch: SearchActivity = {
                    query: data.query || '',
                    results: Array.isArray(data.results) ? data.results : [],
                    done: true,
                    error: data.error || null,
                };
                if (idx >= 0 && s.activeSearches[idx]) {
                    s.activeSearches = s.activeSearches.map((search, searchIdx) =>
                        searchIdx === idx
                            ? {
                                ...search,
                                query: data.query || search.query,
                                results: nextSearch.results,
                                done: true,
                                error: nextSearch.error,
                            }
                            : search
                    );
                } else {
                    s.activeSearches = [...s.activeSearches, nextSearch];
                }
                break;
            }
            case 'url_fetching':
                s.fetchingUrls = [...s.fetchingUrls, { url: data.url, status: 'fetching' }];
                break;
            case 'url_fetched': {
                s.fetchingUrls = s.fetchingUrls.map(f =>
                    f.url === data.url ? { ...f, status: 'done' as const } : f
                );
                s.fetchedContent = [...s.fetchedContent, {
                    url: data.url,
                    title: data.title || '',
                    content: data.preview || '',
                    contentLength: data.content_length || 0,
                    truncated: data.truncated || false,
                }];
                break;
            }
            case 'url_failed':
                s.fetchingUrls = s.fetchingUrls.map(f =>
                    f.url === data.url ? { ...f, status: 'failed' as const, error: data.error } : f
                );
                break;
            // ── Atlas pipeline events ──
            case 'atlas_started':
                s.atlasActive = true;
                s.atlasPhase = 'estimating';
                s.atlasEffort = {
                    k: data.k,
                    difficulty: data.difficulty,
                    tier: data.effort_tier,
                };
                s.atlasCandidates = Array.from({ length: data.k }, (_, i) => ({
                    index: i,
                    score: null,
                    testsPassed: null,
                    testsTotal: null,
                    status: 'pending' as const,
                }));
                break;
            case 'candidate_start':
                s.atlasPhase = 'generating';
                if (s.atlasCandidates[data.index]) {
                    s.atlasCandidates = s.atlasCandidates.map((c, i) =>
                        i === data.index ? { ...c, status: 'generating' } : c
                    );
                }
                // Only reset streaming state for candidate 0 (which streams live).
                // Candidates 1+ run silently — keep candidate 0's output visible.
                if (data.index === 0) {
                    s.streamingText = '';
                    s.streamingThinking = '';
                    s.tokenCount = 0;
                    s.genStartTime = 0;
                }
                break;
            case 'candidate_scored':
                if (s.atlasCandidates[data.index]) {
                    s.atlasCandidates = s.atlasCandidates.map((c, i) =>
                        i === data.index ? {
                            ...c,
                            score: data.score,
                            testsPassed: data.tests_passed ?? null,
                            testsTotal: data.tests_total ?? null,
                            status: 'scored',
                        } : c
                    );
                }
                break;
            case 'candidate_selected':
                s.atlasPhase = 'selecting';
                if (s.atlasCandidates[data.index]) {
                    s.atlasCandidates = s.atlasCandidates.map((c, i) =>
                        i === data.index ? { ...c, status: 'selected' } : c
                    );
                }
                break;
            case 'atlas_testing':
                s.atlasPhase = 'testing';
                break;
            case 'atlas_repair':
                s.atlasPhase = 'repairing';
                break;
            case 'atlas_repair_result':
                break;
            case 'compacting':
                s.isCompacting = true;
                if (data.message) s.warning = data.message;
                break;
            case 'continued':
                s.isCompacting = false;
                s.warning = data.truncated
                    ? (data.message || 'The response still hit the context limit and may be incomplete.')
                    : '';
                break;
            case 'warning':
                s.warning = data.message || '';
                break;
            case 'error':
                s.isCompacting = false;
                s.phase = 'done';
                s.response = `**Error:** ${data.message || 'Unknown error'}`;
                break;
        }
        return s;
    });
}

type ConnectCallback = () => void;

export function connect(onConnected?: ConnectCallback) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws/think`;
    ws = new WS(url, handleEvent);
    if (onConnected) ws.onOpen = onConnected;
    ws.connect();
}

export function disconnect() {
    ws?.disconnect();
    ws = null;
}

export function loadFromHistory(conv: {
    id: string;
    messages: Array<{
        id?: string;
        role: string;
        content: string;
        position?: number;
        thinking?: string;
        draft?: string;
        route?: string;
        specialist_data?: string;
        reflection?: string;
        feedback?: number;
        detected_lang?: string;
    }>;
}) {
    chat.update((s) => {
        s.conversationId = conv.id;
        s.conversation = conv.messages.map((m) => {
            const route = m.route || undefined;
            // Derive isCode from route, or detect HTML for old messages without route.
            // ROUTE_COMPUTER only counts as "code" when detected_lang is "multi" (file markers
            // were used). A prose summary from the tool-call path has detected_lang "text".
            const isCode = route === 'ROUTE_DESIGN' || route === 'ROUTE_CODE'
                || (route === 'ROUTE_COMPUTER' && (m.detected_lang ?? 'text') !== 'text')
                || (m.role === 'assistant' && /^<!doctype\s/i.test(m.content.trim()));

            // Derive detectedLang: use saved value, or fall back from route for older messages
            const detectedLang = m.detected_lang || (
                route === 'ROUTE_DESIGN' ? 'html' :
                route === 'ROUTE_COMPUTER' ? 'multi' : undefined
            );

            // Safe JSON parsing — malformed data must not crash the load
            let specialistData;
            try { specialistData = m.specialist_data ? JSON.parse(m.specialist_data) : undefined; }
            catch { specialistData = undefined; }

            let reflection;
            try { reflection = m.reflection ? JSON.parse(m.reflection) : undefined; }
            catch { reflection = undefined; }

            return {
                role: m.role as 'user' | 'assistant',
                content: m.content,
                messageId: m.id,
                messagePosition: m.position,
                thinking: m.thinking || undefined,
                route,
                isCode,
                detectedLang,
                specialistData,
                reflection,
                feedback: m.feedback,
            };
        });
        s.cancelRequested = false;
        s.phase = 'idle';
        s.events = [];
        s.route = '';
        s.plan = null;
        s.specialistData = null;
        s.review = null;
        s.reflection = null;
        s.response = '';
        s.thinking = '';
        s.draft = '';
        s.draftThinking = '';
        s.streamingText = '';
        s.streamingThinking = '';
        s.validationIssues = [];
        s.editing = false;
        s.warning = '';
        s.undoStack = [];
        clearWorkspaceSessionState(s);
        s.atlasActive = false;
        s.atlasCandidates = [];
        s.atlasPhase = null;
        s.atlasEffort = null;
        return s;
    });
}

export function newConversation() {
    chat.set({ ...initial });
}

export async function revertToTurn(userTurnIdx: number) {
    let sourceConversationId: string | null = null;
    let forkConversation: Array<Record<string, any>> = [];

    chat.update((s) => {
        sourceConversationId = s.conversationId;
        const trimmedConversation = s.conversation.slice(0, userTurnIdx + 1);
        forkConversation = trimmedConversation.map((turn) => ({
            role: turn.role,
            content: turn.content,
            thinking: turn.thinking,
            draftThinking: turn.draftThinking,
            route: turn.route,
            specialistData: turn.specialistData,
            reflection: turn.reflection,
            feedback: turn.feedback,
            detectedLang: turn.detectedLang,
        }));
        s.conversation = trimmedConversation.map((turn) => ({
            ...turn,
            messageId: undefined,
            messagePosition: undefined,
        }));
        s.phase = 'idle';
        s.response = '';
        s.route = '';
        s.plan = null;
        s.specialistData = null;
        s.review = null;
        s.reflection = null;
        s.thinking = '';
        s.draft = '';
        s.draftThinking = '';
        s.events = [];
        s.undoStack = [];
        s.forceClearKvOnNextThink = true;
        clearTransientTurnState(s);
        return s;
    });

    if (!sourceConversationId) {
        activeConversationId.set(null);
        return;
    }

    try {
        const res = await fetch(`/api/conversations/${sourceConversationId}/fork`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conversation: forkConversation }),
        });
        if (!res.ok) {
            throw new Error(`fork failed: ${res.status}`);
        }
        const data = await res.json();
        chat.update((s) => {
            s.conversationId = data.id;
            s.forceClearKvOnNextThink = false;
            return s;
        });
        activeConversationId.set(data.id);
        await loadConversations();
    } catch {
        chat.update((s) => {
            s.conversationId = null;
            return s;
        });
        activeConversationId.set(null);
    }
}

export function setMode(mode: ModeOverride) {
    chat.update((s) => {
        if (s.workspaceId && mode !== 'computer') return s;
        s.modeOverride = s.workspaceId ? 'computer' : mode;
        return s;
    });
}

export function undo() {
    chat.update((s) => {
        if (s.undoStack.length === 0) return s;
        const prev = s.undoStack[s.undoStack.length - 1];
        s.undoStack = s.undoStack.slice(0, -1);
        // Replace last assistant code turn with previous version
        for (let i = s.conversation.length - 1; i >= 0; i--) {
            if (s.conversation[i].role === 'assistant' && s.conversation[i].isCode) {
                s.conversation = [...s.conversation];
                s.conversation[i] = { ...s.conversation[i], content: prev };
                break;
            }
        }
        s.response = prev;
        return s;
    });
}

export async function setFeedback(turnIndex: number, feedback: number) {
    let messageId: string | undefined;
    const unsub = chat.subscribe((s) => {
        messageId = s.conversation[turnIndex]?.messageId;
    });
    unsub();

    if (messageId) {
        await fetch(`/api/messages/${messageId}/feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feedback }),
        });
    }

    chat.update((s) => {
        if (s.conversation[turnIndex]) {
            s.conversation[turnIndex].feedback = feedback;
        }
        return s;
    });
}

export function setAltIndex(turnIdx: number, altIdx: number) {
    chat.update((s) => {
        if (s.conversation[turnIdx]) {
            s.conversation[turnIdx] = { ...s.conversation[turnIdx], altIndex: altIdx };
        }
        return s;
    });
}

export function regenerate(assistantTurnIdx?: number) {
    let lastUserMsg = '';
    let lastAttachments: Attachment[] = [];

    chat.update((s) => {
        // Find the assistant turn to regenerate (default: last one)
        let assIdx = assistantTurnIdx !== undefined ? assistantTurnIdx : s.conversation.length - 1;
        while (assIdx >= 0 && s.conversation[assIdx].role !== 'assistant') assIdx--;
        if (assIdx < 0) return s;

        const assTurn = s.conversation[assIdx];
        _pendingPrevAlts = assTurn.alternatives || [];
        _pendingAlt = assTurn.content;

        // Find the preceding user turn
        let userIdx = assIdx - 1;
        while (userIdx >= 0 && s.conversation[userIdx].role !== 'user') userIdx--;
        if (userIdx < 0) return s;

        lastUserMsg = s.conversation[userIdx].content;
        lastAttachments = s.conversation[userIdx].attachments || [];

        // Truncate conversation to just before the user turn
        s.conversation = s.conversation.slice(0, userIdx);
        return s;
    });

    if (lastUserMsg) {
        sendThink(lastUserMsg, lastAttachments);
    }
}

export function setWorkspaceId(id: string | null) {
    chat.update((s) => {
        applyWorkspaceId(s, id);
        return s;
    });
    try {
        if (id) { // falsy covers null and "" — neither is a valid workspace id
            localStorage.setItem('ct2_workspace_id', id);
        } else {
            localStorage.removeItem('ct2_workspace_id');
        }
    } catch {}
}

/** Restore workspace ID from localStorage. Returns the ID if one was restored, null otherwise. */
export function restoreWorkspace(): string | null {
    try {
        const id = localStorage.getItem('ct2_workspace_id');
        if (id) {
            chat.update((s) => {
                if (!s.workspaceId) {
                    applyWorkspaceId(s, id);
                }
                return s;
            });
            return id;
        }
    } catch {}
    return null;
}

/** Clear the pending command queue (called after TerminalPanel has consumed them). */
export function clearPendingCommands() {
    chat.update(s => { s.pendingCommands = []; return s; });
}

export function clearPendingApproval() {
    chat.update(s => { s.pendingApproval = null; return s; });
}

export function toggleContextFile(path: string) {
    chat.update((s) => {
        const idx = s.contextFiles.indexOf(path);
        s.contextFiles = idx >= 0
            ? s.contextFiles.filter((p) => p !== path)
            : [...s.contextFiles, path];
        return s;
    });
}

export function clearContextFiles() {
    chat.update((s) => { s.contextFiles = []; return s; });
}

export function stopGeneration() {
    ws?.send({ type: 'cancel' });
    chat.update((s) => {
        const partial = s.streamingText || '';
        const thinking = s.streamingThinking || '';
        const fetchedContent = s.fetchedContent.length > 0 ? s.fetchedContent : undefined;
        const activeSearches = s.activeSearches.length > 0
            ? cloneSearchActivities(s.activeSearches)
            : undefined;
        const preserveSavedFiles = s.route === 'ROUTE_COMPUTER' ? [...s.savedFiles] : [];
        const lastTurn = s.conversation[s.conversation.length - 1];
        s.cancelRequested = true;

        if (!partial && lastTurn?.role === 'user') {
            // Nothing generated yet — remove the user turn, go back to idle
            s.conversation = s.conversation.slice(0, -1);
            s.phase = 'idle';
        } else if (partial) {
            // Push partial response as a real assistant turn so it stays
            // in history with feedback + regenerate buttons
            const codeRoute = s.route === 'ROUTE_DESIGN' || s.route === 'ROUTE_CODE';
            s.conversation = [
                ...s.conversation,
                {
                    role: 'assistant',
                    content: partial,
                    isCode: codeRoute,
                    route: s.route,
                    plan: s.plan,
                    specialistData: s.specialistData,
                    thinking: thinking || undefined,
                    activeSearches,
                    fetchedContent,
                },
            ];
            s.response = partial;
            s.thinking = thinking;
            s.phase = 'done';
        } else {
            s.phase = 'idle';
        }

        clearTransientTurnState(s);

        if (partial) {
            s.response = partial;
            s.thinking = thinking;
            s.savedFiles = preserveSavedFiles;
        } else {
            s.route = '';
            s.plan = null;
            s.specialistData = null;
            s.response = '';
            s.thinking = '';
            s.savedFiles = [];
        }

        return s;
    });
}

export async function sendThink(goal: string, attachments: Attachment[] = []) {
    let conv: Turn[] = [];
    let mode: ModeOverride = 'auto';
    let wsId: string | null = null;
    let convId: string | null = null;
    let s_contextFiles: string[] = [];
    let forceClearKv = false;
    const unsub = chat.subscribe((s) => {
        conv = s.conversation;
        mode = s.modeOverride;
        wsId = s.workspaceId;
        convId = s.conversationId;
        s_contextFiles = s.contextFiles;
        forceClearKv = s.forceClearKvOnNextThink;
    });
    unsub();

    // Build current message content first so compaction can reserve room for it.
    let textPrefix = '';
    const imageAtts: Attachment[] = [];
    for (const att of attachments) {
        if (att.type === 'file' && att.textContent) {
            textPrefix += `[File: ${att.name}]\n${att.textContent}\n\n`;
        } else if (att.type === 'image') {
            imageAtts.push(att);
        }
    }

    const fullGoal = textPrefix ? `${textPrefix}${goal}` : goal;

    let goalContent: any = fullGoal;
    if (imageAtts.length > 0) {
        const parts: any[] = [{ type: 'text', text: fullGoal }];
        for (const att of imageAtts) {
            parts.push({ type: 'image_url', image_url: { url: att.dataUrl } });
        }
        goalContent = parts;
    }

    // Build conversation for backend — convert attachments to multimodal content
    let backendConv = conv.map(t => {
        if (t.attachments && t.attachments.length > 0) {
            let text = t.content;
            const images: Attachment[] = [];
            for (const att of t.attachments) {
                if (att.type === 'file' && att.textContent) {
                    text = `[File: ${att.name}]\n${att.textContent}\n\n${text}`;
                } else if (att.type === 'image') {
                    images.push(att);
                }
            }
            if (images.length > 0) {
                const content: any[] = [{ type: 'text', text }];
                for (const att of images) {
                    content.push({ type: 'image_url', image_url: { url: att.dataUrl } });
                }
                return { role: t.role, content };
            }
            return { role: t.role, content: text };
        }
        return { role: t.role, content: t.content };
    });

    // Auto-compact before the model context fills up.
    // Reserve room for the new user message and for the next reply, otherwise small
    // contexts like 2K can still start a turn that gets clipped mid-generation.
    if (_contextSize > 0 && conv.length >= 2) {
        const historyTokens = backendConv.reduce(
            (acc: number, t: any) => acc + estimateContentTokens(t.content),
            0
        );
        const pendingUserTokens = estimateContentTokens(goalContent);
        const overhead = Math.min(800, Math.round(_contextSize * 0.4));
        const effectiveCtx = Math.max(512, _contextSize - overhead);
        const replyReserve = Math.min(
            1024,
            Math.max(256, Math.round(effectiveCtx * 0.45))
        );
        const projectedPrompt = historyTokens + pendingUserTokens;
        if (projectedPrompt > effectiveCtx - replyReserve || historyTokens / effectiveCtx >= 0.75) {
            chat.update(s => { s.isCompacting = true; return s; });
            try {
                const res = await fetch('/api/compact', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ conversation: backendConv }),
                });
                if (res.ok) {
                    const data = await res.json();
                    if (data.conversation?.length > 0) {
                        backendConv = data.conversation;
                        // Replace frontend conversation with the compacted view
                        chat.update(s => {
                            const summaryTurn: Turn = {
                                role: 'assistant',
                                content: data.conversation[0].content,
                                isCompacted: true,
                            };
                            // Preserve latest code turn if compaction produced one
                            const codeTurn = data.conversation.length > 1
                                ? data.conversation[data.conversation.length - 1]
                                : null;
                            s.conversation = codeTurn
                                ? [summaryTurn, { role: 'assistant', content: codeTurn.content, isCode: true }]
                                : [summaryTurn];
                            s.isCompacting = false;
                            return s;
                        });
                        // Update `conv` so position count is correct
                        conv = get(chat).conversation;
                    } else {
                        chat.update(s => { s.isCompacting = false; return s; });
                    }
                } else {
                    chat.update(s => { s.isCompacting = false; return s; });
                }
            } catch {
                chat.update(s => { s.isCompacting = false; return s; });
            }
        }
    }

    chat.update((s) => {
        s.conversation = [...s.conversation, {
            role: 'user', content: goal,
            attachments: attachments.length > 0 ? attachments : undefined,
        }];
        s.cancelRequested = false;
        s.events = [];
        s.route = '';
        s.plan = null;
        s.specialistData = null;
        s.review = null;
        s.reflection = null;
        s.response = '';
        s.thinking = '';
        s.draft = '';
        s.draftThinking = '';
        s.checklist = [];
        s.validationIssues = [];
        s.streamingText = '';
        s.streamingThinking = '';
        s.editing = false;
        s.warning = '';
        s.phase = 'routing';
        s.tokenCount = 0;
        s.genStartTime = 0;
        s.tokensPerSec = 0;
        s.savedFiles = [];
        s.fetchingUrls = [];
        s.fetchedContent = [];
        s.activeSearches = [];
        s.atlasActive = false;
        s.atlasCandidates = [];
        s.atlasPhase = null;
        s.atlasEffort = null;
        s.forceClearKvOnNextThink = false;
        return s;
    });

    const prefs = get(preferences);
    const searchEnabled = prefs.webSearchEnabled;
    const effectiveMode: ModeOverride = wsId ? 'computer' : mode;
    const atlasSettings = prefs.atlasMode ? {
        atlasMode: true,
        effortMode: prefs.atlasEffortMode,
        effortLevel: prefs.atlasEffortLevel,
        selfVerification: prefs.atlasSelfVerification,
        multiPerspective: prefs.atlasMultiPerspective,
        iterativeRefinement: prefs.atlasIterativeRefinement,
    } : null;

    ws?.send({
        type: 'think',
        goal: goalContent,
        conversation: backendConv,
        conversation_id: convId,
        position: conv.length,
        ...(effectiveMode !== 'auto' ? { mode_override: effectiveMode } : {}),
        ...(wsId ? { workspace_id: wsId } : {}),
        ...(!prefs.designRefinement ? { skip_refinement: true } : {}),
        ...(atlasSettings ? { atlas: atlasSettings } : {}),
        ...(s_contextFiles.length > 0 ? { context_files: s_contextFiles } : {}),
        ...(searchEnabled ? { search_capability: true } : {}),
        ...(forceClearKv ? { force_clear_kv: true } : {}),
        ...(prefs.requireCommandApproval ? { require_command_approval: true } : {}),
    });
}
