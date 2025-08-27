export default async function handler(req, res) {
  // 只允许 POST 请求
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed. Use POST.' });
  }

  try {
    const { mode = 'all', today_only = false } = req.body;
    
    // 验证参数
    const validModes = ['link', 'market', 'position', 'all'];
    if (!validModes.includes(mode)) {
      return res.status(400).json({ 
        error: 'Invalid mode. Must be one of: link, market, position, all' 
      });
    }

    // 调用 GitHub API 触发 Actions
    const response = await fetch(
      `https://api.github.com/repos/YiZhiYuanYuan-qyy/fund_sync/actions/workflows/run-notion-pipeline.yml/dispatches`,
      {
        method: 'POST',
        headers: {
          'Authorization': `token ${process.env.GITHUB_TOKEN}`,
          'Accept': 'application/vnd.github.v3+json',
          'User-Agent': 'Vercel-Trigger-Pipeline'
        },
        body: JSON.stringify({
          ref: 'main',
          inputs: {
            mode: mode,
            today_only: today_only.toString()
          }
        })
      }
    );

    if (!response.ok) {
      const errorText = await response.text();
      console.error('GitHub API error:', response.status, errorText);
      return res.status(response.status).json({ 
        error: 'Failed to trigger GitHub Actions',
        details: errorText
      });
    }

    console.log(`Successfully triggered pipeline with mode: ${mode}, today_only: ${today_only}`);
    
        // 根据模式决定等待策略
    if (mode === 'all' || mode === 'market') {
        // 需要抓取外部数据的模式：立即返回，避免 Vercel 超时
        console.log('External data fetching mode, returning immediately to avoid Vercel timeout...');
        
        // 异步触发 fund-daily-view（等待足够时间让数据抓取完成）
        setTimeout(async () => {
            try {
                console.log('Checking fund-sync workflow status and triggering fund-daily-view...');
                
                // 检查 workflow 状态
                const workflowResponse = await fetch(
                    `https://api.github.com/repos/YiZhiYuanYuan-qyy/fund_sync/actions/workflows/run-notion-pipeline.yml/runs?per_page=1`,
                    {
                        headers: {
                            'Authorization': `token ${process.env.GITHUB_TOKEN}`,
                            'Accept': 'application/vnd.github.v3+json',
                            'User-Agent': 'Vercel-Trigger-Pipeline'
                        }
                    }
                );
                
                if (workflowResponse.ok) {
                    const workflowData = await workflowResponse.json();
                    const latestRun = workflowData.workflow_runs[0];
                    
                    if (latestRun && latestRun.status === 'completed') {
                        console.log(`Fund-sync workflow completed with conclusion: ${latestRun.conclusion}`);
                        
                        if (latestRun.conclusion === 'success') {
                            // 成功完成后触发 fund-daily-view
                            console.log('Triggering fund-daily-view calculation...');
                            const dailyViewResponse = await fetch(
                                `https://api.github.com/repos/YiZhiYuanYuan-qyy/fund_daily_view/actions/workflows/run-daily-view.yml/dispatches`,
                                {
                                    method: 'POST',
                                    headers: {
                                        'Authorization': `token ${process.env.GITHUB_TOKEN}`,
                                        'Accept': 'application/vnd.github.v3+json',
                                        'User-Agent': 'Vercel-Trigger-Pipeline'
                                    },
                                    body: JSON.stringify({
                                        ref: 'main',
                                        inputs: {
                                            mode: 'profit'
                                        }
                                    })
                                }
                            );
                            
                            if (dailyViewResponse.ok) {
                                console.log('Successfully triggered fund-daily-view calculation');
                            } else {
                                console.log('Failed to trigger fund-daily-view calculation:', dailyViewResponse.status);
                            }
                        } else {
                            console.log('Fund-sync workflow failed, skipping fund-daily-view trigger');
                        }
                    } else {
                        console.log(`Fund-sync workflow still running: ${latestRun?.status}`);
                        // 如果还在运行，再等一段时间
                        setTimeout(async () => {
                            try {
                                console.log('Retrying fund-daily-view trigger...');
                                const dailyViewResponse = await fetch(
                                    `https://api.github.com/repos/YiZhiYuanYuan-qyy/fund_daily_view/actions/workflows/run-daily-view.yml/dispatches`,
                                    {
                                        method: 'POST',
                                        headers: {
                                            'Authorization': `token ${process.env.GITHUB_TOKEN}`,
                                            'Accept': 'application/vnd.github.v3+json',
                                            'User-Agent': 'Vercel-Trigger-Pipeline'
                                        },
                                        body: JSON.stringify({
                                            ref: 'main',
                                            inputs: {
                                                mode: 'profit'
                                            }
                                        })
                                    }
                                );
                                
                                if (dailyViewResponse.ok) {
                                    console.log('Successfully triggered fund-daily-view calculation on retry');
                                } else {
                                    console.log('Failed to trigger fund-daily-view calculation on retry:', dailyViewResponse.status);
                                }
                            } catch (error) {
                                console.log('Error on retry:', error.message);
                            }
                        }, 60000); // 再等1分钟
                    }
                }
            } catch (error) {
                console.log('Error checking workflow status:', error.message);
            }
        }, 60000); // 1分钟后检查状态
    } else {
        // 纯 Notion 操作模式：快速触发，无需等待
        console.log('Pure Notion operation mode, triggering fund-daily-view immediately...');
        
        try {
            const dailyViewResponse = await fetch(
                `https://api.github.com/repos/YiZhiYuanYuan-qyy/fund_daily_view/actions/workflows/run-daily-view.yml/dispatches`,
                {
                    method: 'POST',
                    headers: {
                        'Authorization': `token ${process.env.GITHUB_TOKEN}`,
                        'Accept': 'application/vnd.github.v3+json',
                        'User-Agent': 'Vercel-Trigger-Pipeline'
                    },
                    body: JSON.stringify({
                        ref: 'main',
                        inputs: {
                            mode: 'profit'
                        }
                    })
                }
            );
            
            if (dailyViewResponse.ok) {
                console.log('Successfully triggered fund-daily-view calculation');
            } else {
                console.log('Failed to trigger fund-daily-view calculation:', dailyViewResponse.status);
            }
        } catch (error) {
            console.log('Error triggering fund-daily-view calculation:', error.message);
        }
    }
    
    return res.status(200).json({
      success: true,
      message: 'Pipeline triggered successfully',
      mode: mode,
      today_only: today_only,
      timestamp: new Date().toISOString(),
      note: mode === 'all' || mode === 'market' ? 'Fund-sync triggered successfully. fund-daily-view will be triggered automatically after data update completion.' : 'All operations completed.'
    });

  } catch (error) {
    console.error('Error triggering pipeline:', error);
    return res.status(500).json({ 
      error: 'Internal server error',
      message: error.message 
    });
  }
}
