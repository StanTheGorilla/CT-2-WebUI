"""Fallback component library for the Precision-Design pipeline.

Provides neutral, responsive HTML fallbacks for every standard component type.
Each fallback uses Tailwind utility classes with sm:/md:/lg: breakpoints,
neutral colors (gray, slate, white), and PLACEHOLDER markers for content.
"""

FALLBACKS: dict[str, str] = {
    "navbar": """<nav id="{id}" class="bg-white border-b border-gray-200 px-4 sm:px-6 lg:px-8 py-3">
  <!-- PLACEHOLDER: Replace with actual content -->
  <div class="max-w-7xl mx-auto flex items-center justify-between">
    <a href="#" class="text-xl font-bold text-gray-900">Brand</a>
    <button data-toggle="hamburger" class="sm:hidden p-2 text-gray-600 hover:text-gray-900" aria-label="Toggle menu">
      <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/>
      </svg>
    </button>
    <ul data-hamburger-menu class="hidden sm:flex sm:items-center sm:space-x-6 text-sm font-medium text-gray-700">
      <li><a href="#" class="hover:text-gray-900 transition-colors">Home</a></li>
      <li><a href="#" class="hover:text-gray-900 transition-colors">About</a></li>
      <li><a href="#" class="hover:text-gray-900 transition-colors">Services</a></li>
      <li><a href="#" class="hover:text-gray-900 transition-colors">Contact</a></li>
    </ul>
  </div>
</nav>""",

    "hero": """<section id="{id}" class="bg-slate-50 py-16 sm:py-20 md:py-28 lg:py-32">
  <!-- PLACEHOLDER: Replace with actual content -->
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
    <h1 class="text-3xl sm:text-4xl md:text-5xl lg:text-6xl font-extrabold text-gray-900 tracking-tight">
      Welcome to Our Site
    </h1>
    <p class="mt-4 sm:mt-6 text-base sm:text-lg md:text-xl text-gray-600 max-w-2xl mx-auto">
      A brief description of what we do and why it matters to you.
    </p>
    <div class="mt-8 sm:mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
      <a href="#" class="inline-block rounded-lg bg-gray-900 px-6 py-3 text-sm font-semibold text-white hover:bg-gray-800 transition-colors">
        Get Started
      </a>
      <a href="#" class="inline-block rounded-lg border border-gray-300 px-6 py-3 text-sm font-semibold text-gray-700 hover:bg-gray-100 transition-colors">
        Learn More
      </a>
    </div>
  </div>
</section>""",

    "features": """<section id="{id}" class="bg-white py-16 sm:py-20 md:py-24">
  <!-- PLACEHOLDER: Replace with actual content -->
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    <div class="text-center mb-12 sm:mb-16">
      <h2 class="text-2xl sm:text-3xl md:text-4xl font-bold text-gray-900">Features</h2>
      <p class="mt-3 text-base sm:text-lg text-gray-600 max-w-2xl mx-auto">Everything you need, nothing you don't.</p>
    </div>
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-8">
      <div class="p-6 rounded-xl border border-gray-200 hover:shadow-md transition-shadow">
        <div class="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center mb-4">
          <span class="text-gray-500 text-lg font-bold">1</span>
        </div>
        <h3 class="text-lg font-semibold text-gray-900">Feature One</h3>
        <p class="mt-2 text-sm text-gray-600">A short description of this feature and its benefits.</p>
      </div>
      <div class="p-6 rounded-xl border border-gray-200 hover:shadow-md transition-shadow">
        <div class="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center mb-4">
          <span class="text-gray-500 text-lg font-bold">2</span>
        </div>
        <h3 class="text-lg font-semibold text-gray-900">Feature Two</h3>
        <p class="mt-2 text-sm text-gray-600">A short description of this feature and its benefits.</p>
      </div>
      <div class="p-6 rounded-xl border border-gray-200 hover:shadow-md transition-shadow">
        <div class="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center mb-4">
          <span class="text-gray-500 text-lg font-bold">3</span>
        </div>
        <h3 class="text-lg font-semibold text-gray-900">Feature Three</h3>
        <p class="mt-2 text-sm text-gray-600">A short description of this feature and its benefits.</p>
      </div>
    </div>
  </div>
</section>""",

    "testimonials": """<section id="{id}" class="bg-slate-50 py-16 sm:py-20 md:py-24">
  <!-- PLACEHOLDER: Replace with actual content -->
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    <div class="text-center mb-12 sm:mb-16">
      <h2 class="text-2xl sm:text-3xl md:text-4xl font-bold text-gray-900">What People Say</h2>
      <p class="mt-3 text-base sm:text-lg text-gray-600">Trusted by teams everywhere.</p>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
      <blockquote class="bg-white p-6 rounded-xl border border-gray-200">
        <p class="text-gray-700 text-sm leading-relaxed">"This product changed how we work. Highly recommended for any team."</p>
        <footer class="mt-4 flex items-center space-x-3">
          <div class="w-10 h-10 rounded-full bg-gray-200"></div>
          <div>
            <p class="text-sm font-semibold text-gray-900">Jane Doe</p>
            <p class="text-xs text-gray-500">CEO, Company</p>
          </div>
        </footer>
      </blockquote>
      <blockquote class="bg-white p-6 rounded-xl border border-gray-200">
        <p class="text-gray-700 text-sm leading-relaxed">"Outstanding quality and support. We saw results within the first week."</p>
        <footer class="mt-4 flex items-center space-x-3">
          <div class="w-10 h-10 rounded-full bg-gray-200"></div>
          <div>
            <p class="text-sm font-semibold text-gray-900">John Smith</p>
            <p class="text-xs text-gray-500">CTO, Startup</p>
          </div>
        </footer>
      </blockquote>
      <blockquote class="bg-white p-6 rounded-xl border border-gray-200 hidden lg:block">
        <p class="text-gray-700 text-sm leading-relaxed">"Simple, effective, and beautifully designed. Exactly what we needed."</p>
        <footer class="mt-4 flex items-center space-x-3">
          <div class="w-10 h-10 rounded-full bg-gray-200"></div>
          <div>
            <p class="text-sm font-semibold text-gray-900">Alice Lee</p>
            <p class="text-xs text-gray-500">Designer, Agency</p>
          </div>
        </footer>
      </blockquote>
    </div>
  </div>
</section>""",

    "cta": """<section id="{id}" class="bg-gray-900 py-16 sm:py-20 md:py-24">
  <!-- PLACEHOLDER: Replace with actual content -->
  <div class="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
    <h2 class="text-2xl sm:text-3xl md:text-4xl font-bold text-white">Ready to Get Started?</h2>
    <p class="mt-4 text-base sm:text-lg text-gray-300 max-w-xl mx-auto">
      Join thousands of satisfied customers. Start your free trial today.
    </p>
    <div class="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
      <a href="#" class="inline-block rounded-lg bg-white px-6 py-3 text-sm font-semibold text-gray-900 hover:bg-gray-100 transition-colors">
        Start Free Trial
      </a>
      <a href="#" class="inline-block rounded-lg border border-gray-500 px-6 py-3 text-sm font-semibold text-gray-300 hover:text-white hover:border-white transition-colors">
        Contact Sales
      </a>
    </div>
  </div>
</section>""",

    "footer": """<footer id="{id}" class="bg-gray-900 text-gray-400 py-12 sm:py-16">
  <!-- PLACEHOLDER: Replace with actual content -->
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-8">
      <div class="col-span-2 sm:col-span-3 lg:col-span-1 mb-4 lg:mb-0">
        <span class="text-lg font-bold text-white">Brand</span>
        <p class="mt-2 text-sm">Building great products since 2024.</p>
      </div>
      <div>
        <h4 class="text-sm font-semibold text-white mb-3">Product</h4>
        <ul class="space-y-2 text-sm">
          <li><a href="#" class="hover:text-white transition-colors">Features</a></li>
          <li><a href="#" class="hover:text-white transition-colors">Pricing</a></li>
          <li><a href="#" class="hover:text-white transition-colors">Docs</a></li>
        </ul>
      </div>
      <div>
        <h4 class="text-sm font-semibold text-white mb-3">Company</h4>
        <ul class="space-y-2 text-sm">
          <li><a href="#" class="hover:text-white transition-colors">About</a></li>
          <li><a href="#" class="hover:text-white transition-colors">Blog</a></li>
          <li><a href="#" class="hover:text-white transition-colors">Careers</a></li>
        </ul>
      </div>
      <div>
        <h4 class="text-sm font-semibold text-white mb-3">Legal</h4>
        <ul class="space-y-2 text-sm">
          <li><a href="#" class="hover:text-white transition-colors">Privacy</a></li>
          <li><a href="#" class="hover:text-white transition-colors">Terms</a></li>
        </ul>
      </div>
    </div>
    <div class="mt-10 pt-6 border-t border-gray-800 text-sm text-center">
      &copy; 2024 Brand. All rights reserved.
    </div>
  </div>
</footer>""",

    "contact": """<section id="{id}" class="bg-white py-16 sm:py-20 md:py-24">
  <!-- PLACEHOLDER: Replace with actual content -->
  <div class="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
    <div class="text-center mb-10 sm:mb-12">
      <h2 class="text-2xl sm:text-3xl md:text-4xl font-bold text-gray-900">Contact Us</h2>
      <p class="mt-3 text-base sm:text-lg text-gray-600">We'd love to hear from you.</p>
    </div>
    <form data-validate="contact" class="space-y-6">
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-6">
        <div>
          <label for="{id}-name" class="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input type="text" id="{id}-name" name="name" required
            class="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:border-gray-500 focus:ring-1 focus:ring-gray-500 outline-none transition">
        </div>
        <div>
          <label for="{id}-email" class="block text-sm font-medium text-gray-700 mb-1">Email</label>
          <input type="email" id="{id}-email" name="email" required
            class="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:border-gray-500 focus:ring-1 focus:ring-gray-500 outline-none transition">
        </div>
      </div>
      <div>
        <label for="{id}-message" class="block text-sm font-medium text-gray-700 mb-1">Message</label>
        <textarea id="{id}-message" name="message" rows="5" required
          class="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:border-gray-500 focus:ring-1 focus:ring-gray-500 outline-none transition resize-y"></textarea>
      </div>
      <div class="text-center">
        <button type="submit"
          class="inline-block rounded-lg bg-gray-900 px-8 py-3 text-sm font-semibold text-white hover:bg-gray-800 transition-colors">
          Send Message
        </button>
      </div>
    </form>
  </div>
</section>""",

    "pricing": """<section id="{id}" class="bg-slate-50 py-16 sm:py-20 md:py-24">
  <!-- PLACEHOLDER: Replace with actual content -->
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    <div class="text-center mb-12 sm:mb-16">
      <h2 class="text-2xl sm:text-3xl md:text-4xl font-bold text-gray-900">Pricing</h2>
      <p class="mt-3 text-base sm:text-lg text-gray-600">Simple, transparent pricing for everyone.</p>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-5xl mx-auto">
      <div class="bg-white rounded-xl border border-gray-200 p-6 sm:p-8 flex flex-col">
        <h3 class="text-lg font-semibold text-gray-900">Free</h3>
        <p class="mt-1 text-sm text-gray-500">For individuals</p>
        <p class="mt-4 text-3xl sm:text-4xl font-bold text-gray-900">$0<span class="text-base font-normal text-gray-500">/mo</span></p>
        <ul class="mt-6 space-y-3 text-sm text-gray-600 flex-1">
          <li class="flex items-center"><span class="mr-2 text-gray-400">&#10003;</span>Basic features</li>
          <li class="flex items-center"><span class="mr-2 text-gray-400">&#10003;</span>1 project</li>
          <li class="flex items-center"><span class="mr-2 text-gray-400">&#10003;</span>Community support</li>
        </ul>
        <a href="#" class="mt-8 block text-center rounded-lg border border-gray-300 px-6 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-100 transition-colors">
          Get Started
        </a>
      </div>
      <div class="bg-white rounded-xl border-2 border-gray-900 p-6 sm:p-8 flex flex-col relative">
        <span class="absolute -top-3 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-xs font-semibold px-3 py-1 rounded-full">Popular</span>
        <h3 class="text-lg font-semibold text-gray-900">Pro</h3>
        <p class="mt-1 text-sm text-gray-500">For teams</p>
        <p class="mt-4 text-3xl sm:text-4xl font-bold text-gray-900">$29<span class="text-base font-normal text-gray-500">/mo</span></p>
        <ul class="mt-6 space-y-3 text-sm text-gray-600 flex-1">
          <li class="flex items-center"><span class="mr-2 text-gray-400">&#10003;</span>All Free features</li>
          <li class="flex items-center"><span class="mr-2 text-gray-400">&#10003;</span>Unlimited projects</li>
          <li class="flex items-center"><span class="mr-2 text-gray-400">&#10003;</span>Priority support</li>
        </ul>
        <a href="#" class="mt-8 block text-center rounded-lg bg-gray-900 px-6 py-2.5 text-sm font-semibold text-white hover:bg-gray-800 transition-colors">
          Get Started
        </a>
      </div>
      <div class="bg-white rounded-xl border border-gray-200 p-6 sm:p-8 flex flex-col">
        <h3 class="text-lg font-semibold text-gray-900">Enterprise</h3>
        <p class="mt-1 text-sm text-gray-500">For organizations</p>
        <p class="mt-4 text-3xl sm:text-4xl font-bold text-gray-900">Custom</p>
        <ul class="mt-6 space-y-3 text-sm text-gray-600 flex-1">
          <li class="flex items-center"><span class="mr-2 text-gray-400">&#10003;</span>All Pro features</li>
          <li class="flex items-center"><span class="mr-2 text-gray-400">&#10003;</span>SSO &amp; SAML</li>
          <li class="flex items-center"><span class="mr-2 text-gray-400">&#10003;</span>Dedicated support</li>
        </ul>
        <a href="#" class="mt-8 block text-center rounded-lg border border-gray-300 px-6 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-100 transition-colors">
          Contact Us
        </a>
      </div>
    </div>
  </div>
</section>""",
}


def get_fallback(component_type: str, component_id: str) -> str:
    """Return fallback HTML for the given component type.

    Args:
        component_type: One of the standard component types (navbar, hero, etc.).
        component_id: The DOM id to assign to the root element.

    Returns:
        Rendered HTML string with the component_id inserted, or an empty
        commented-out placeholder if the type is unknown.
    """
    template = FALLBACKS.get(component_type)
    if template is None:
        return f'<div id="{component_id}"><!-- PLACEHOLDER: No fallback for type "{component_type}" --></div>'
    return template.format(id=component_id)
