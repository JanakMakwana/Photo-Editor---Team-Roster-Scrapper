import React from 'react';
import type { Metadata } from 'next';
import { Theme } from '@radix-ui/themes';
import './globals.css';

export const metadata: Metadata = {
  title: 'VeloRoster Pro • Athletic Roster & 180×180 Headshot Studio',
  description: 'Standardized 180×180 transparent headshot formatting, AI background removal, and multi-league athletic roster ingestion. Developed by Ecstaticloud Technologies.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700;800&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
      </head>
      <body>
        <Theme appearance="light" accentColor="blue" grayColor="slate" radius="medium">
          {children}
        </Theme>
      </body>
    </html>
  );
}
