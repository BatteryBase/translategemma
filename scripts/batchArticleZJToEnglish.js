const fetch = require('node-fetch');
const arangodb = require('../../utils/arangodb')
const deepl = require('deepl-node');

const ZJToEnglish = async ({sourceArticle}={}) => {
    
    const texts = [];

    const dealContent = ({content}={}) =>{
        if (content instanceof Array) {
            for (let i = 0; i < content.length; i++) {
                if (content[i].type == "text") {
                    // console.log(1111, content[i].text)
                    // text = `${text}${content[i].text}`
                    // console.log(3333, text)

                    if (content[i].text.trim()) {
                        texts.push({
                          node: content[i],
                          text: content[i].text
                        });
                      }
                }
                dealContent({content: content[i].content})
            }
        }
    }

    dealContent({content: sourceArticle.content.content})

    let text = texts.map(t => t.text)

    // const response = await fetch(`https://api.deepl.com/v2/translate`, {
    //     method: 'POST',
    //     // mode: 'no-cors',
    //     headers: {
    //         'Content-Type': 'application/json',
    //         'Authorization': "DeepL-Auth-Key b8bf9322-958f-400d-945d-9f65fafb1b6c"
    //     },
    //     body: JSON.stringify({
    //         "text": text,
    //         "target_lang": "EN"
    //     })
    // });

    // const response = await fetch(`https://api-free.deepl.com/v2/translate`, {
    //     method: 'POST',
    //     // mode: 'no-cors',
    //     headers: {
    //         'Content-Type': 'application/json',
    //         'Authorization': "DeepL-Auth-Key 00d6237e-9ced-4dd8-b96f-b9fa6517d0b5:fx"
    //     },
    //     body: JSON.stringify({
    //         "text": text,
    //         "target_lang": "EN"
    //     })
    // });

    // let translations = await response.json()

    // console.log(1111, translations)

    // translations = translations.translations;

    // let translations
    // try {
    //     translations = await translator.translateText(
    //         text,
    //         "ZH",
    //         "en-GB",
    //         { glossary: glossaryId }
    //     );
    // } catch (error) {
    //     console.log(1111)
    //     console.log(error)
    //     return -1;
    // }
    
    const url = 'http://127.0.0.1:8022/api/translate/batch';
    const data = {
        "texts": text,
        "target_lang": "en",
        "source_lang": "zh"
    };

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // 'Authorization': 'Bearer your_token_here' // 如有认证
      },
      body: JSON.stringify(data)
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`HTTP ${response.status}: ${errorText}`);
    }

    const result = await response.json();

    texts.forEach((t, i) => {
        t.node.text = result.results[i].result;
    });

    console.log('content success')

    let otherContent = []

    otherContent.push(sourceArticle.summary ? sourceArticle.summary : "总结")
    otherContent.push(sourceArticle.title ? sourceArticle.title : "标题")
    otherContent.push(sourceArticle.text ? sourceArticle.text : "文本内容")
    otherContent.push(sourceArticle.index ? sourceArticle.index : "空")

    // const responseOther = await fetch(`https://api.deepl.com/v2/translate`, {
    //     method: 'POST',
    //     // mode: 'no-cors',
    //     headers: {
    //         'Content-Type': 'application/json',
    //         'Authorization': "DeepL-Auth-Key b8bf9322-958f-400d-945d-9f65fafb1b6c"
    //     },
    //     body: JSON.stringify({
    //         "text": otherContent,
    //         "target_lang": "EN"
    //     })
    // });

    // const responseOther = await fetch(`https://api-free.deepl.com/v2/translate`, {
    //     method: 'POST',
    //     // mode: 'no-cors',
    //     headers: {
    //         'Content-Type': 'application/json',
    //         'Authorization': "DeepL-Auth-Key 00d6237e-9ced-4dd8-b96f-b9fa6517d0b5:fx"
    //     },
    //     body: JSON.stringify({
    //         "text": otherContent,
    //         "target_lang": "EN"
    //     })
    // });

    // let translationsOther = await responseOther.json()
    
    // translationsOther = translationsOther.translations;

    // console.log(otherContent)

    // let translationsOther
    // try {
    //     translationsOther = await translator.translateText(
    //         otherContent,
    //         "ZH",
    //         "en-GB",
    //         { glossary: glossaryId }
    //     );
    // } catch (error) {
    //     console.log(2222)
    //     console.log(error)
    //     return -1;
    // }

    const dataOtherContent = {
        "texts": otherContent,
        "target_lang": "en",
        "source_lang": "zh"
    };

    const responseOtherContent = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        // 'Authorization': 'Bearer your_token_here' // 如有认证
      },
      body: JSON.stringify(dataOtherContent)
    });

    if (!responseOtherContent.ok) {
      const errorText = await responseOtherContent.text();
      throw new Error(`HTTP ${responseOtherContent.status}: ${errorText}`);
    }

    const resultOtherContent = await responseOtherContent.json();

    console.log('otherContent success')

      // 2025.4.20 两篇文章改为1篇文章（2个字段）
      // 孟博士 只有中文转英文（没有英文转中文）
    // const cursorNewArticle = await arangodb.query(`
    // insert @data into my_nyz_article return NEW
    // `,{
    //     data:{
    //         isVIP: sourceArticle.isVIP,
    //         tagKey: sourceArticle.tagKey,
    //         score: sourceArticle.score,
    //         attachment: sourceArticle.attachment,
    //         cover: sourceArticle.cover,
    //         summary: translationsOther[0].text,
    //         isEmpty: null,
    //         updateTime: Date.now(),
    //         applyNZK: sourceArticle.applyNZK,
    //         isDraft: null,
    //         draftTime: null,
    //         title: translationsOther[1].text,
    //         content: sourceArticle.content,
    //         text: translationsOther[2].text,
    //         wordNumber: translationsOther[2].text.length,
    //         original: sourceArticle.original,
    //         index: translationsOther[3].text,
    //         status: 1,
    //         language: "english",
    //         sourceArticleKey: sourceArticle._key
    //     }
    // })

    // const newArticleInfo = await cursorNewArticle.all()

    // if (newArticleInfo.length) {
    //     const cursorUpdateSourceArticle = await arangodb.query(`
    //     for a in my_nyz_article
    //     filter a._key == "${sourceArticle._key}" and a.status == 1
    //     update a with @data in my_nyz_article
    //     return NEW
    //     `,{
    //         data: {
    //             hasDeepl: 1,
    //             englishArticleKey: newArticleInfo[0]._key
    //         }
    //     })

    //     const updateSourceArticle = await cursorUpdateSourceArticle.all()
    // }

        const cursorUpdateSourceArticle = await arangodb.query(`
        for a in my_nyz_article
        filter a._key == "${sourceArticle._key}" and a.status == 1
        update a with @data in my_nyz_article
        return NEW
        `,{
            data: {
                hasZhangJun: 1,
                // englishArticleKey: newArticleInfo[0]._key
                summary_english: resultOtherContent.results[0].result,
                title_english: resultOtherContent.results[1].result,
                content_english: sourceArticle.content,
                text_english: resultOtherContent.results[2].result,
                wordNumber_english: resultOtherContent.results[2].result.length,
                index_english: resultOtherContent.results[3].result,
                updateTime: Date.now()
            }
        })

        const updateSourceArticle = await cursorUpdateSourceArticle.all()

        console.log('update success')

    return 1;
}

module.exports = async(req, res, next) => {
    const { articleKey, time=10 } = req.body;
    try {    
        let articles

        if (articleKey) {
            const articleCursor = await arangodb.query('FOR a IN my_nyz_article filter a._key == @articleKey RETURN a._key', {
                'articleKey': articleKey
            })
    
            articles = await articleCursor.all()
        } else {
            // const articleCursor = await arangodb.query(`
            //     FOR a IN my_nyz_article filter a.hasDeepl != 1 and a.status == 1 and !a.isEmpty and !a.isDraft and IS_OBJECT(a.content) 
            //     filter a.tagKey == "9328448145"
            //     sort TO_NUMBER(a._key) asc
            //     RETURN a._key`, {
                
            // })

            // 2026.7.9 汪刚 先取消 and a.passNZK == 1 
            const articleCursor = await arangodb.query(`
                FOR a IN my_nyz_article 
                filter a.hasZhangJun != 1 and a.hasDeepl != 1 and a.status == 1 and !a.isEmpty and !a.isDraft and IS_OBJECT(a.content) and IS_ARRAY(a.content.content)
                sort TO_NUMBER(a._key) asc
                limit 0, ${time}
                RETURN a._key`, {
                
            })

            articles = await articleCursor.all()
        }

        if (articles.length == 0) {
            return res.json({
                status: 201,
                msg: '文章不存在'
            });
        }

        console.log('articles', articles)

        // const translator = new deepl.Translator('00d6237e-9ced-4dd8-b96f-b9fa6517d0b5:fx', { serverUrl: 'https://api-free.deepl.com' });
        // const translator = new deepl.Translator('648e4dd9-9682-45b7-9bd2-1c88ba215432', { serverUrl: 'https://api.deepl.com' });
        // const translator = new deepl.Translator('6d186bb7-c4f4-4431-8efe-eb5cd8994dd3', { serverUrl: 'https://api.deepl.com' });
        // const translator = new deepl.Translator('c154ee4b-2ba7-42b4-89b3-23c9235aac24', { serverUrl: 'https://api.deepl.com' });
        // const translator = new deepl.Translator('8d000ad1-500e-407f-b318-f62767b6df6b', { serverUrl: 'https://api.deepl.com' });
        // const translator = new deepl.Translator('009dcd00-fe02-4cc1-a4d1-62f010fea1ef', { serverUrl: 'https://api.deepl.com' });
        // const translator = new deepl.Translator('664c8ebf-80eb-4471-be4a-a07bea4c7418', { serverUrl: 'https://api.deepl.com' });
        // const translator = new deepl.Translator('54370715-9f22-44c0-a995-bc71a77f66a6', { serverUrl: 'https://api.deepl.com' });
        // const translator = new deepl.Translator('46d32fd7-bdf6-45cd-8b61-06bcec08c6e5', { serverUrl: 'https://api.deepl.com' });
        // const translator = new deepl.Translator('54147f54-9df3-48ab-97da-1113de551d49', { serverUrl: 'https://api.deepl.com' });
        // const translator = new deepl.Translator('cae7972f-9ece-4a27-bbbf-b93d5b90a235', { serverUrl: 'https://api.deepl.com' });
        // const translator = new deepl.Translator('e9ebcc23-fddd-4a25-9487-e3716a0ad3e3', { serverUrl: 'https://api.deepl.com' });
        
        // const csvFilePath = './glossary.csv';
        // const glossary = await translator.createGlossaryWithCsv(
        //     'nenghe glossary',
        //     'ZH',
        //     'en-GB',
        //     csvFilePath);
    
        // console.log('glossary info', glossary)

        let startTime = Date.now()

        for (let i = 0; i < articles.length; i++) {
            const articleCursor = await arangodb.query('FOR a IN my_nyz_article filter a._key == @articleKey RETURN a', {
                'articleKey': articles[i]
            })
    
            const article = await articleCursor.all()
            if (article.length) {
                // try {
                    console.log('articles info', article[0]._key, article[0].title)
                    let resultT = await ZJToEnglish({sourceArticle: article[0]})

                    if (resultT == -1) {
                        break;
                    }
                // } catch (error) {
                //     console.log(error)
                // }
            }
        }

        let endTime = Date.now()

        console.log(`-------------------batchArticleZJToEnglish end ${endTime-startTime}---------------------`)

        // await translator.deleteGlossary(glossary.glossaryId);

        return res.json({
            status: '200',
            msg: 'OK'
        });
    } catch (error) {
        console.log(error)
        // return next(error);
        return res.json({
            status: 201,
            msg: '服务器异常'
        });
    }
}