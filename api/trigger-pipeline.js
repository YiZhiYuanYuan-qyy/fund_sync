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
    
    return res.status(200).json({
      success: true,
      message: 'Pipeline triggered successfully',
      mode: mode,
      today_only: today_only,
      timestamp: new Date().toISOString()
    });

  } catch (error) {
    console.error('Error triggering pipeline:', error);
    return res.status(500).json({ 
      error: 'Internal server error',
      message: error.message 
    });
  }
}
