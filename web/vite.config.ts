import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	build: {
		rollupOptions: {
			output: {
				manualChunks(id) {
					if (!id.includes('node_modules')) return;
					if (id.includes('katex')) return 'katex';
					if (id.includes('marked')) return 'markdown';
					if (id.includes('highlight.js')) return 'highlight';
					return 'vendor';
				},
			},
		},
	},
	server: {
		proxy: {
			'/api': 'http://localhost:8000',
			'/ws': {
				target: 'ws://localhost:8000',
				ws: true,
			},
		},
	},
});
