'use client';

import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

export const demoButtonVariants = cva(
  'inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        outline: 'border border-input bg-background hover:bg-accent hover:text-accent-foreground',
        ghost: 'hover:bg-accent hover:text-accent-foreground',
      },
      size: {
        default: 'h-9 px-4',
        sm: 'h-8 px-3 text-xs',
        icon: 'size-9',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
);

export type DemoButtonProps = React.ComponentProps<'button'> &
  VariantProps<typeof demoButtonVariants>;

/** Judges-workspace button. Local to /meta-ai-hackathon-demo; the classic
 *  workspace keeps its own Button untouched. asChild is intentionally
 *  unsupported: pass href-free actions only. */
export function DemoButton({ variant, size, className, type, ...props }: DemoButtonProps) {
  return (
    <button
      type={type ?? 'button'}
      className={cn(demoButtonVariants({ variant, size }), className)}
      {...props}
    />
  );
}
