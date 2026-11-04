import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';
// Locally styled shadcn/ui Button pattern, attributed in README.
const buttonVariants = cva('button', { variants: { variant: { default: 'primary', outline: 'outline', secondary: 'secondary', destructive: 'btn-destructive', ghost: 'btn-ghost' } }, defaultVariants: { variant: 'default' } });
export function Button({ className, variant, asChild = false, appearance = 'default', ...props }: React.ComponentProps<'button'> & VariantProps<typeof buttonVariants> & { asChild?: boolean; appearance?: 'default' | 'workspace' }) {
  const Comp = asChild ? Slot : 'button';
  return <Comp className={cn(appearance === 'workspace' ? className : buttonVariants({ variant, className }))} {...props} />;
}
