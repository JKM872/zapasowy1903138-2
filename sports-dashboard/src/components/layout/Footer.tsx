import { Github, Heart } from 'lucide-react'

export function Footer() {
  return (
    <footer className="border-t bg-muted/40">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4 sm:px-6 text-xs text-muted-foreground">
        <p className="flex items-center gap-1">
          Made with <Heart className="h-3 w-3 text-rose-500" /> Sports&nbsp;Predictor
        </p>
        <div className="flex items-center gap-4">
          <a href="/pricing" className="hover:text-foreground transition-colors">Pricing</a>
          <a
            href="https://github.com/JKM872/zapasowy1903138-2"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 hover:text-foreground transition-colors"
          >
            <Github className="h-3.5 w-3.5" />
            Open Source
          </a>
        </div>
      </div>
    </footer>
  )
}
