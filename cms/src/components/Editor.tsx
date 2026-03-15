'use client';

import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Underline } from '@tiptap/extension-underline';
import { Image } from '@tiptap/extension-image';
import { Link } from '@tiptap/extension-link';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useEffect } from 'react';

interface EditorProps {
  content: string;
  onChange: (content: string) => void;
  placeholder?: string;
  className?: string;
}

export function Editor({ content, onChange, placeholder = '开始编写...', className }: EditorProps) {
  const editor = useEditor({
    extensions: [
      // StarterKit already includes: Bold, Italic, Strike, Code, Heading,
      // Blockquote, BulletList, OrderedList, ListItem, HorizontalRule, CodeBlock
      StarterKit,
      // These are NOT in StarterKit — safe to add separately
      Underline,
      Image,
      Link.configure({ openOnClick: false }),
    ],
    content,
    onUpdate: ({ editor }) => {
      onChange(editor.getHTML());
    },
  });

  // Sync external content changes (e.g. when user selects a different post)
  useEffect(() => {
    if (editor && content !== editor.getHTML()) {
      editor.commands.setContent(content, { emitUpdate: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, editor]);

  if (!editor) {
    return (
      <div className="min-h-[400px] p-6 border border-gray-200 rounded-md bg-white flex items-center justify-center text-gray-400">
        编辑器加载中...
      </div>
    );
  }

  return (
    <div className={cn('w-full', className)}>
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-1 p-2 border border-b-0 border-gray-200 rounded-t-md bg-gray-50">
        <Button variant="ghost" size="sm" onClick={() => editor.chain().focus().toggleBold().run()} className={cn(editor.isActive('bold') && 'bg-blue-100 text-blue-600')}>
          B
        </Button>
        <Button variant="ghost" size="sm" onClick={() => editor.chain().focus().toggleItalic().run()} className={cn(editor.isActive('italic') && 'bg-blue-100 text-blue-600')}>
          I
        </Button>
        <Button variant="ghost" size="sm" onClick={() => editor.chain().focus().toggleUnderline().run()} className={cn(editor.isActive('underline') && 'bg-blue-100 text-blue-600')}>
          U
        </Button>
        <Button variant="ghost" size="sm" onClick={() => editor.chain().focus().toggleStrike().run()} className={cn(editor.isActive('strike') && 'bg-blue-100 text-blue-600')}>
          S
        </Button>

        <span className="w-px h-5 bg-gray-300 mx-1" />

        <Button variant="ghost" size="sm" onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} className={cn(editor.isActive('heading', { level: 1 }) && 'bg-blue-100 text-blue-600')}>
          H1
        </Button>
        <Button variant="ghost" size="sm" onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} className={cn(editor.isActive('heading', { level: 2 }) && 'bg-blue-100 text-blue-600')}>
          H2
        </Button>
        <Button variant="ghost" size="sm" onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()} className={cn(editor.isActive('heading', { level: 3 }) && 'bg-blue-100 text-blue-600')}>
          H3
        </Button>

        <span className="w-px h-5 bg-gray-300 mx-1" />

        <Button variant="ghost" size="sm" onClick={() => editor.chain().focus().toggleBlockquote().run()} className={cn(editor.isActive('blockquote') && 'bg-blue-100 text-blue-600')}>
          &ldquo;&rdquo;
        </Button>
        <Button variant="ghost" size="sm" onClick={() => editor.chain().focus().toggleBulletList().run()} className={cn(editor.isActive('bulletList') && 'bg-blue-100 text-blue-600')}>
          •
        </Button>
        <Button variant="ghost" size="sm" onClick={() => editor.chain().focus().toggleOrderedList().run()} className={cn(editor.isActive('orderedList') && 'bg-blue-100 text-blue-600')}>
          1.
        </Button>

        <span className="w-px h-5 bg-gray-300 mx-1" />

        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            const url = window.prompt('输入图片URL');
            if (url) editor.chain().focus().setImage({ src: url }).run();
          }}
        >
          图片
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            const url = window.prompt('输入链接URL');
            if (url) editor.chain().focus().setLink({ href: url }).run();
          }}
          className={cn(editor.isActive('link') && 'bg-blue-100 text-blue-600')}
        >
          链接
        </Button>
      </div>

      {/* Content area */}
      <div className="min-h-[400px] p-6 border border-gray-200 rounded-b-md bg-white prose prose-sm max-w-none">
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}
