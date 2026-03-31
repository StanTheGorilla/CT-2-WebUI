import { Marked } from 'marked';
import hljs from 'highlight.js';
import katex from 'katex';
import 'highlight.js/styles/github.css';
import 'katex/dist/katex.min.css';

const marked = new Marked({
    gfm: true,
    breaks: true,
    renderer: {
        code({ text, lang }: { text: string; lang?: string }) {
            const language = lang && hljs.getLanguage(lang) ? lang : undefined;
            const highlighted = language
                ? hljs.highlight(text, { language }).value
                : hljs.highlightAuto(text).value;
            return `<pre><code class="hljs${language ? ` language-${language}` : ''}">${highlighted}</code></pre>`;
        },
    },
});

function renderMath(text: string): string {
    // Display math: $$...$$
    text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_, math) => {
        try {
            return katex.renderToString(math.trim(), { displayMode: true, throwOnError: false });
        } catch {
            return `<pre>${math}</pre>`;
        }
    });
    // Inline math: $...$  (but not $$)
    text = text.replace(/(?<!\$)\$([^\$\n]+?)\$(?!\$)/g, (_, math) => {
        try {
            return katex.renderToString(math.trim(), { displayMode: false, throwOnError: false });
        } catch {
            return `<code>${math}</code>`;
        }
    });
    return text;
}

export function render(text: string): string {
    if (!text) return '';
    const withMath = renderMath(text);
    return marked.parse(withMath) as string;
}
