"use client";
import React from 'react';
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts';
import { format } from 'date-fns';

interface MainChartProps {
  data: {
    forecast_prices?: number[];
    forecast_dates?: string[];
    lower_ci?: number[];
    upper_ci?: number[];
  } | null;
}

export function MainChart({ data }: MainChartProps) {
  if (!data || !data.forecast_prices) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm">
        Waiting for data...
      </div>
    );
  }

  // 1. Construct Data for Recharts
  // We align the forecast dates with the prices and confidence intervals
  const chartData = data.forecast_prices.map((price: number, i: number) => ({
    date: data.forecast_dates?.[i] ?? String(i + 1),
    forecast: price,
    // Create the range array [lower, upper] for the shaded area
    range: [data.lower_ci?.[i] || price * 0.95, data.upper_ci?.[i] || price * 1.05]
  }));

  return (
    <div className="w-full h-full min-h-[350px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <defs>
            {/* Gradient for the Confidence Cone */}
            <linearGradient id="colorCone" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#ea580c" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#ea580c" stopOpacity={0.05} />
            </linearGradient>
          </defs>
          
          <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
          
          <XAxis 
            dataKey="date" 
            stroke="#666" 
            tick={{ fill: '#666', fontSize: 11 }} 
            tickFormatter={(str) => {
              try { return format(new Date(str), 'MMM d'); } catch { return str; }
            }}
            minTickGap={30}
          />
          
          <YAxis 
            domain={['auto', 'auto']} 
            stroke="#666" 
            tick={{ fill: '#666', fontSize: 11 }}
            tickFormatter={(val) => `$${val.toFixed(0)}`}
            width={50}
          />
          
          <Tooltip 
            contentStyle={{ backgroundColor: '#1a1a1a', borderColor: '#333', color: '#eee', fontSize: '12px' }}
            itemStyle={{ color: '#eee' }}
            formatter={(value) => [typeof value === 'number' ? `$${value.toFixed(2)}` : String(value), '']}
            labelFormatter={(label) => `Date: ${label}`}
          />
          
          {/* The Confidence Cone (Shaded Area) */}
          <Area 
            type="monotone" 
            dataKey="range" 
            stroke="none" 
            fill="url(#colorCone)" 
            name="Confidence Interval"
          />
          
          {/* The Forecast Line */}
          <Line 
            type="monotone" 
            dataKey="forecast" 
            stroke="#ea580c" 
            strokeWidth={2} 
            dot={false} 
            activeDot={{ r: 4 }}
            name="Forecast Price"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
