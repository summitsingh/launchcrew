import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';
// Locally styled shadcn/ui Button pattern, attributed in README.
const buttonVariants = cva('button', { variants: { variant: { default: 'primary', outline: 'outline', secondary: 'secondary' } }, defaultVariants: { variant: 'default' } });
export function Button({ className, variant, asChild = false, ...props }: React.ComponentProps<'button'> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : 'button';
  return <Comp className={cn(buttonVariants({ variant, className }))} {...props} />;
}
