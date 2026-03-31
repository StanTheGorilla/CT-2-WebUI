"""Interaction snippet library for the Precision-Design pipeline.

Provides self-contained <script> blocks for common UI interactions.
Each snippet uses data-* attributes for targeting and degrades gracefully
if the expected DOM elements are absent.
"""

SNIPPETS: dict[str, str] = {
    "hamburger-toggle": """<script>
(function() {
  var toggles = document.querySelectorAll('[data-toggle="hamburger"]');
  if (!toggles.length) return;
  toggles.forEach(function(btn) {
    btn.addEventListener('click', function() {
      var menu = document.querySelector('[data-hamburger-menu]');
      if (!menu) return;
      var isHidden = menu.classList.contains('hidden');
      if (isHidden) {
        menu.classList.remove('hidden');
        menu.classList.add('flex', 'flex-col', 'absolute', 'top-full', 'left-0', 'w-full', 'bg-white', 'border-b', 'border-gray-200', 'p-4', 'space-y-3', 'z-50');
      } else {
        menu.classList.add('hidden');
        menu.classList.remove('flex', 'flex-col', 'absolute', 'top-full', 'left-0', 'w-full', 'bg-white', 'border-b', 'border-gray-200', 'p-4', 'space-y-3', 'z-50');
      }
      btn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
    });
  });
})();
</script>""",

    "smooth-scroll": """<script>
(function() {
  var links = document.querySelectorAll('[data-smooth-scroll]');
  if (!links.length) links = document.querySelectorAll('a[href^="#"]');
  if (!links.length) return;
  links.forEach(function(link) {
    link.addEventListener('click', function(e) {
      var href = this.getAttribute('href') || this.getAttribute('data-smooth-scroll');
      if (!href || href === '#') return;
      var target = document.querySelector(href);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
})();
</script>""",

    "accordion": """<script>
(function() {
  var triggers = document.querySelectorAll('[data-accordion-trigger]');
  if (!triggers.length) return;
  triggers.forEach(function(trigger) {
    trigger.addEventListener('click', function() {
      var content = this.nextElementSibling;
      if (!content || !content.hasAttribute('data-accordion-content')) {
        content = this.parentElement.querySelector('[data-accordion-content]');
      }
      if (!content) return;
      var isOpen = content.style.maxHeight && content.style.maxHeight !== '0px';
      if (isOpen) {
        content.style.maxHeight = '0px';
        content.style.overflow = 'hidden';
        this.setAttribute('aria-expanded', 'false');
      } else {
        content.style.maxHeight = content.scrollHeight + 'px';
        content.style.overflow = 'hidden';
        this.setAttribute('aria-expanded', 'true');
      }
    });
  });
  // Initialize all accordion contents as collapsed
  var contents = document.querySelectorAll('[data-accordion-content]');
  contents.forEach(function(el) {
    el.style.maxHeight = '0px';
    el.style.overflow = 'hidden';
    el.style.transition = 'max-height 0.3s ease';
  });
})();
</script>""",

    "form-validation": """<script>
(function() {
  var forms = document.querySelectorAll('[data-validate]');
  if (!forms.length) return;
  forms.forEach(function(form) {
    form.setAttribute('novalidate', '');
    form.addEventListener('submit', function(e) {
      var isValid = true;
      var fields = form.querySelectorAll('[required]');
      // Clear previous errors
      form.querySelectorAll('.validation-error').forEach(function(el) { el.remove(); });
      fields.forEach(function(field) {
        field.classList.remove('border-red-500');
        var value = field.value.trim();
        var valid = true;
        if (!value) {
          valid = false;
        } else if (field.type === 'email' && !/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(value)) {
          valid = false;
        }
        if (!valid) {
          isValid = false;
          field.classList.add('border-red-500');
          var msg = document.createElement('p');
          msg.className = 'validation-error text-red-500 text-xs mt-1';
          msg.textContent = field.type === 'email' && value ? 'Please enter a valid email.' : 'This field is required.';
          field.parentNode.appendChild(msg);
        }
      });
      if (!isValid) {
        e.preventDefault();
        var firstError = form.querySelector('.border-red-500');
        if (firstError) firstError.focus();
      }
    });
  });
})();
</script>""",

    "dark-mode-toggle": """<script>
(function() {
  var toggles = document.querySelectorAll('[data-toggle="darkmode"]');
  if (!toggles.length) return;
  function applyTheme(dark) {
    if (dark) {
      document.documentElement.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('theme', 'light');
    }
  }
  // Initialize from stored preference or system preference
  var stored = localStorage.getItem('theme');
  if (stored === 'dark' || (!stored && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    applyTheme(true);
  }
  toggles.forEach(function(btn) {
    btn.addEventListener('click', function() {
      var isDark = document.documentElement.classList.contains('dark');
      applyTheme(!isDark);
    });
  });
})();
</script>""",

    "carousel": """<script>
(function() {
  var carousels = document.querySelectorAll('[data-carousel]');
  if (!carousels.length) return;
  carousels.forEach(function(carousel) {
    var track = carousel.querySelector('[data-carousel-track]');
    var slides = track ? track.children : [];
    if (!slides.length) return;
    var index = 0;
    var prevBtn = carousel.querySelector('[data-carousel-prev]');
    var nextBtn = carousel.querySelector('[data-carousel-next]');
    function goTo(i) {
      index = (i + slides.length) % slides.length;
      Array.from(slides).forEach(function(slide, idx) {
        slide.style.display = idx === index ? '' : 'none';
      });
    }
    goTo(0);
    if (prevBtn) prevBtn.addEventListener('click', function() { goTo(index - 1); });
    if (nextBtn) nextBtn.addEventListener('click', function() { goTo(index + 1); });
  });
})();
</script>""",

    "modal": """<script>
(function() {
  var openers = document.querySelectorAll('[data-modal-open]');
  if (!openers.length) return;
  function openModal(id) {
    var modal = document.getElementById(id);
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    // Close on backdrop click
    modal.addEventListener('click', function handler(e) {
      if (e.target === modal) {
        closeModal(id);
        modal.removeEventListener('click', handler);
      }
    });
    // Close on Escape
    document.addEventListener('keydown', function handler(e) {
      if (e.key === 'Escape') {
        closeModal(id);
        document.removeEventListener('keydown', handler);
      }
    });
  }
  function closeModal(id) {
    var modal = document.getElementById(id);
    if (!modal) return;
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  }
  openers.forEach(function(btn) {
    btn.addEventListener('click', function() {
      var target = this.getAttribute('data-modal-open');
      if (target) openModal(target);
    });
  });
  document.querySelectorAll('[data-modal-close]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var modal = this.closest('[id]');
      if (modal) closeModal(modal.id);
    });
  });
})();
</script>""",

    "scroll-reveal": """<script>
(function() {
  var elements = document.querySelectorAll('[data-scroll-reveal]');
  if (!elements.length) return;
  // Set initial hidden state
  elements.forEach(function(el) {
    el.style.opacity = '0';
    el.style.transform = 'translateY(20px)';
    el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
  });
  if (!('IntersectionObserver' in window)) {
    // Fallback: just show everything
    elements.forEach(function(el) {
      el.style.opacity = '1';
      el.style.transform = 'translateY(0)';
    });
    return;
  }
  var observer = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (entry.isIntersecting) {
        entry.target.style.opacity = '1';
        entry.target.style.transform = 'translateY(0)';
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
  elements.forEach(function(el) { observer.observe(el); });
})();
</script>""",
}


def get_snippets(snippet_ids: list[str]) -> str:
    """Return concatenated <script> blocks for the requested interaction types.

    Args:
        snippet_ids: List of snippet identifiers (e.g. ["hamburger-toggle", "smooth-scroll"]).

    Returns:
        A single string containing all matched <script> blocks joined by newlines.
        Unknown snippet_ids are silently skipped.
    """
    parts = []
    seen = set()
    for sid in snippet_ids:
        if sid in SNIPPETS and sid not in seen:
            parts.append(SNIPPETS[sid])
            seen.add(sid)
    return "\n".join(parts)
