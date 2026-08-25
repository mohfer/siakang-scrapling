import { defineConfig } from 'vitepress'

// https://vitepress.dev/reference/site-config
export default defineConfig({
  lang: 'en-US',
  title: 'siakang-scrapling',
  description:
    'Python library for scraping Siakang Untirta — class schedules, study results and semesters — over pure HTTP.',
  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    nav: [
      { text: 'Guide', link: '/guide/api-reference' },
      { text: 'Errors & Responses', link: '/guide/errors-and-responses' },
      { text: 'Troubleshooting', link: '/guide/troubleshooting' }
    ],
    sidebar: [
      {
        text: 'Guide',
        items: [
          { text: 'Getting Started', link: '/guide/getting-started' },
          { text: 'API Reference', link: '/guide/api-reference' },
          { text: 'Errors & Responses', link: '/guide/errors-and-responses' },
          { text: 'CLI Examples', link: '/guide/cli' },
          { text: 'How It Works', link: '/guide/how-it-works' },
          { text: 'Troubleshooting', link: '/guide/troubleshooting' }
        ]
      }
    ],
    socialLinks: [{ icon: 'github', link: 'https://github.com/mohfer/siakang-scrapling' }],
    outline: { level: [2, 3], label: 'On this page' },
    docFooter: { prev: 'Previous', next: 'Next' },
    lastUpdated: false
  }
})
