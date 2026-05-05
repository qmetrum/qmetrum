"use client";
import React, { useEffect, useState } from 'react';
import { Clock, Newspaper } from 'lucide-react';
import { assetApi, type AssetNewsResponse } from '@/lib/api';

interface NewsItem {
  title: string;
  publisher?: string;
  link?: string;
  timestamp?: string;
}

export function NewsFeed({ ticker }: { ticker: string }) {
  const [news, setNews] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fetchNews = async () => {
      if (!ticker) return;
      setLoading(true);
      try {
        const res: AssetNewsResponse = await assetApi.news(ticker, 10);
        setNews(res.items ?? []);
      } catch (err) {
        console.error("Failed to fetch news", err);
      } finally {
        setLoading(false);
      }
    };

    fetchNews();
  }, [ticker]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center gap-2 mb-3 px-1">
        <Newspaper size={14} className="text-orange-500" />
        <h2 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
          Latest News: {ticker}
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto pr-2 space-y-3 custom-scrollbar">
        {loading ? (
          <div className="text-gray-600 text-xs animate-pulse">Scanning wires...</div>
        ) : news.length === 0 ? (
          <div className="text-gray-600 text-xs">No recent news found.</div>
        ) : (
          news.map((item, idx) => (
            <a 
              key={`${item.link ?? item.title}-${idx}`} 
              href={item.link ?? "#"} 
              target="_blank" 
              rel="noopener noreferrer"
              className="block bg-[#1a1a1a] p-3 rounded border border-gray-800 hover:border-orange-500/50 transition-colors group"
            >
              <h3 className="text-gray-200 text-sm font-medium leading-snug mb-2 group-hover:text-orange-400">
                {item.title}
              </h3>
              <div className="flex justify-between items-center text-[10px] text-gray-500">
                <span className="flex items-center gap-1">
                  <span className="font-bold text-gray-400">{item.publisher ?? "Unknown"}</span>
                </span>
                <span className="flex items-center gap-1">
                  <Clock size={10} />
                  {(item.timestamp ?? "").split(' ')[0] || "—"} {/* Just show date */}
                </span>
              </div>
            </a>
          ))
        )}
      </div>
    </div>
  );
}
